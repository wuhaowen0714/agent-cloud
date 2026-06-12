import uuid

import pytest
from agent_cloud_backend.sandbox.docker_provisioner import DockerProvisioner


class _FakeContainer:
    def __init__(self, name):
        self.name = name
        self.ports = {"50051/tcp": [{"HostPort": "49222"}]}
        self.status = "running"
        self.stopped = False
        self.removed = False

    def reload(self):
        pass

    def stop(self, timeout=5):
        self.stopped = True

    def remove(self, force=False):
        self.removed = True


class _FakeContainers:
    def __init__(self):
        self.run_kwargs = None
        self.by_name = {}

    def run(self, **kwargs):
        self.run_kwargs = kwargs
        c = _FakeContainer(kwargs["name"])
        self.by_name[kwargs["name"]] = c
        return c

    def get(self, name):
        from docker.errors import NotFound

        if name not in self.by_name:
            raise NotFound(name)
        return self.by_name[name]

    def list(self, all=False, filters=None):
        return list(self.by_name.values())


class _FakeNetwork:
    def __init__(self, name):
        self.name = name
        self.containers = []
        self.connected = []
        self.disconnected = []
        self.removed = False

    def connect(self, c, **kw):
        self.connected.append(c)
        self.containers.append(c)

    def disconnect(self, c, **kw):
        self.disconnected.append(c)

    def reload(self):
        pass

    def remove(self):
        self.removed = True


class _FakeNetworks:
    def __init__(self):
        self.by_name = {}
        self.created = []

    def create(self, name, **kw):
        n = _FakeNetwork(name)
        self.by_name[name] = n
        self.created.append(name)
        return n

    def get(self, name):
        from docker.errors import NotFound

        if name not in self.by_name:
            raise NotFound(name)
        return self.by_name[name]

    def list(self, filters=None):
        return list(self.by_name.values())


class _FakeClient:
    def __init__(self):
        self.containers = _FakeContainers()
        self.networks = _FakeNetworks()


async def test_spawn_publish_mode_mounts_workspace_and_returns_localhost_endpoint(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="img:1", network_mode="publish", client=client
    )
    uid = uuid.uuid4()
    sandbox_id, endpoint, _ = await prov.spawn(uid)

    kw = client.containers.run_kwargs
    assert kw["volumes"] == {f"{tmp_path}/{uid}/workspace": {"bind": "/workspace", "mode": "rw"}}
    assert kw["image"] == "img:1"
    assert kw["detach"] is True
    assert kw["cap_drop"] == ["ALL"]
    assert "no-new-privileges" in kw["security_opt"][0]
    assert kw["init"] is True  # tini 当 PID1 收僵尸,防超时杀掉的后台进程累积撞 pids_limit
    assert kw["labels"]["managed-by"] == "agent-cloud"
    assert kw["labels"]["user_id"] == str(uid)
    assert kw["ports"] == {"50051/tcp": None}
    assert kw["memswap_limit"] == kw["mem_limit"]  # 禁 swap(防内存上限被翻倍)
    assert "/tmp" in kw["tmpfs"]  # /tmp 走 tmpfs
    assert kw["name"] == f"acsbx-{sandbox_id}"
    assert endpoint == "127.0.0.1:49222"


async def test_alive_network_mode_checks_container_running(tmp_path):
    # network 模式:health_check 不能从 backend gRPC 探(不在沙箱专属网),改查容器 Running
    client = _FakeClient()
    prov = DockerProvisioner(
        host_root=str(tmp_path),
        image="img:1",
        network_mode="network",
        worker_container="w",
        client=client,
    )
    _, endpoint, _ = await prov.spawn(uuid.uuid4())  # endpoint = acsbx-<id>:50051(容器名)
    assert await prov.alive(endpoint) is True  # 容器 running → 活
    client.containers.by_name[endpoint.rsplit(":", 1)[0]].status = "exited"
    assert await prov.alive(endpoint) is False  # 容器停了 → 死(触发重建)


async def test_alive_network_mode_false_when_container_gone(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(
        host_root=str(tmp_path),
        image="img:1",
        network_mode="network",
        worker_container="w",
        client=client,
    )
    assert await prov.alive("acsbx-nonexistent:50051") is False  # 容器不存在 → 死


async def test_alive_fail_open_on_daemon_error(tmp_path):
    # docker daemon 瞬断(非 NotFound 异常)→ fail-open 视为存活,不误杀健康沙箱(审查 L1)
    class _BoomContainers(_FakeContainers):
        def get(self, name):
            raise RuntimeError("daemon connection reset")

    class _BoomClient:
        def __init__(self):
            self.containers = _BoomContainers()
            self.networks = _FakeNetworks()

    prov = DockerProvisioner(
        host_root=str(tmp_path),
        image="img:1",
        network_mode="network",
        worker_container="w",
        client=_BoomClient(),
    )
    assert await prov.alive("acsbx-whatever:50051") is True


async def test_stop_is_idempotent_when_container_missing(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(host_root=str(tmp_path), image="img:1", client=client)
    await prov.stop(uuid.uuid4())  # 不存在 → 不抛


async def test_stop_stops_and_removes(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(host_root=str(tmp_path), image="img:1", client=client)
    sandbox_id, _, _ = await prov.spawn(uuid.uuid4())
    await prov.stop(sandbox_id)
    c = client.containers.by_name[f"acsbx-{sandbox_id}"]
    assert c.stopped and c.removed


def test_allow_net_false_raises(tmp_path):
    # 不静默假装支持出网限制 → fail-loud(spec §9)
    with pytest.raises(ValueError):
        DockerProvisioner(
            host_root=str(tmp_path), image="img:1", allow_net=False, client=_FakeClient()
        )


async def test_spawn_removes_container_when_no_port_published(tmp_path):
    # run 成功但没拿到发布端口 → 必须清掉容器,不留「在跑却没登记」的孤儿
    class _NoPortContainer(_FakeContainer):
        def __init__(self, name):
            super().__init__(name)
            self.ports = {}

    class _NoPortContainers(_FakeContainers):
        def run(self, **kwargs):
            self.run_kwargs = kwargs
            c = _NoPortContainer(kwargs["name"])
            self.by_name[kwargs["name"]] = c
            return c

    class _NoPortClient:
        def __init__(self):
            self.containers = _NoPortContainers()

    client = _NoPortClient()
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="img:1", network_mode="publish", client=client
    )
    with pytest.raises(RuntimeError):
        await prov.spawn(uuid.uuid4())
    c = next(iter(client.containers.by_name.values()))
    assert c.removed is True


# ── per-sandbox 网络隔离(spec B;mock client 验证 docker API 调用)──


async def test_spawn_network_mode_creates_dedicated_net_and_connects_worker(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(
        host_root=str(tmp_path),
        image="img:1",
        network_mode="network",
        worker_container="wkr",
        client=client,
    )
    sid, ep, _ = await prov.spawn(uuid.uuid4())
    net_name = f"acsbx-net-{sid}"
    assert net_name in client.networks.created  # 起了专属网络
    assert client.containers.run_kwargs["network"] == net_name  # 沙箱接入它(非共享 net)
    assert "wkr" in client.networks.by_name[net_name].connected  # worker 被接入
    assert ep == f"acsbx-{sid}:50051"


async def test_network_mode_requires_worker_container(tmp_path):
    prov = DockerProvisioner(
        host_root=str(tmp_path),
        image="img:1",
        network_mode="network",
        worker_container="",
        client=_FakeClient(),
    )
    with pytest.raises(ValueError):
        await prov.spawn(uuid.uuid4())


async def test_stop_network_mode_removes_dedicated_net(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(
        host_root=str(tmp_path),
        image="img:1",
        network_mode="network",
        worker_container="wkr",
        client=client,
    )
    sid, _, _ = await prov.spawn(uuid.uuid4())
    await prov.stop(sid)
    net = client.networks.by_name[f"acsbx-net-{sid}"]
    assert "wkr" in net.disconnected and net.removed  # 断开 worker + 删网络


async def test_publish_mode_uses_no_dedicated_net(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="img:1", network_mode="publish", client=client
    )
    await prov.spawn(uuid.uuid4())
    assert client.networks.created == []  # publish 模式不建 per-sandbox 网络
