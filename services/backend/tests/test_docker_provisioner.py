import uuid

import pytest
from agent_cloud_backend.sandbox.docker_provisioner import DockerProvisioner


class _FakeContainer:
    def __init__(self, name):
        self.name = name
        self.ports = {"50051/tcp": [{"HostPort": "49222"}]}
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


class _FakeClient:
    def __init__(self):
        self.containers = _FakeContainers()


async def test_spawn_publish_mode_mounts_workspace_and_returns_localhost_endpoint(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="img:1", network_mode="publish", client=client
    )
    uid = uuid.uuid4()
    sandbox_id, endpoint = await prov.spawn(uid)

    kw = client.containers.run_kwargs
    assert kw["volumes"] == {f"{tmp_path}/{uid}/workspace": {"bind": "/workspace", "mode": "rw"}}
    assert kw["image"] == "img:1"
    assert kw["detach"] is True
    assert kw["cap_drop"] == ["ALL"]
    assert "no-new-privileges" in kw["security_opt"][0]
    assert kw["labels"]["managed-by"] == "agent-cloud"
    assert kw["labels"]["user_id"] == str(uid)
    assert kw["ports"] == {"50051/tcp": None}
    assert kw["memswap_limit"] == kw["mem_limit"]  # 禁 swap(防内存上限被翻倍)
    assert "/tmp" in kw["tmpfs"]  # /tmp 走 tmpfs
    assert kw["name"] == f"acsbx-{sandbox_id}"
    assert endpoint == "127.0.0.1:49222"


async def test_spawn_network_mode_uses_container_name_endpoint(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="img:1", network_mode="network",
        network="acnet", client=client,
    )
    sandbox_id, endpoint = await prov.spawn(uuid.uuid4())
    kw = client.containers.run_kwargs
    assert kw["network"] == "acnet"
    assert "ports" not in kw
    assert endpoint == f"acsbx-{sandbox_id}:50051"


async def test_stop_is_idempotent_when_container_missing(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(host_root=str(tmp_path), image="img:1", client=client)
    await prov.stop(uuid.uuid4())  # 不存在 → 不抛


async def test_stop_stops_and_removes(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(host_root=str(tmp_path), image="img:1", client=client)
    sandbox_id, _ = await prov.spawn(uuid.uuid4())
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
