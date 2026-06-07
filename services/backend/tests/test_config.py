from agent_cloud_backend.config import Settings


def test_sandbox_provisioner_defaults():
    s = Settings(_env_file=None)
    assert s.sandbox_provisioner == "inprocess"
    assert s.sandbox_image == "agent-cloud-sandbox:latest"
    assert s.sandbox_docker_network_mode == "publish"
    assert s.sandbox_idle_ttl_seconds == 1800
    assert s.sandbox_reap_interval_seconds == 120
    assert s.sandbox_allow_net is True


def test_sandbox_host_root_defaults_to_base_root():
    s = Settings(_env_file=None)
    # 未单独配 host_root 时回退到 sandbox_base_root(开发机 backend 在宿主,二者相同)
    assert s.effective_sandbox_host_root == s.sandbox_base_root


def test_sandbox_provisioner_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_SANDBOX_PROVISIONER", "docker")
    monkeypatch.setenv("AGENT_CLOUD_SANDBOX_HOST_ROOT", "/srv/ac/sandboxes")
    s = Settings()
    assert s.sandbox_provisioner == "docker"
    assert s.effective_sandbox_host_root == "/srv/ac/sandboxes"
