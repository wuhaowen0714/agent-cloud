from agent_cloud_backend.config import Settings
from agent_cloud_backend.sandbox.deps import build_provisioner
from agent_cloud_backend.sandbox.docker_provisioner import DockerProvisioner
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner


def test_build_provisioner_inprocess_by_default():
    s = Settings(_env_file=None)
    assert isinstance(build_provisioner(s), InProcessProvisioner)


def test_build_provisioner_docker_when_configured(monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_SANDBOX_PROVISIONER", "docker")
    monkeypatch.setenv("AGENT_CLOUD_SANDBOX_HOST_ROOT", "/srv/ac")
    s = Settings()
    # 不连真 Docker:注入假 client
    prov = build_provisioner(s, docker_client=object())
    assert isinstance(prov, DockerProvisioner)
    assert prov._host_root == "/srv/ac"
    assert prov._image == s.sandbox_image
