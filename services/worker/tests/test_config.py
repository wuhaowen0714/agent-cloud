from agent_cloud_worker.config import WorkerSettings


def test_defaults():
    s = WorkerSettings()
    assert s.grpc_port == 50052
    assert s.openai_base_url == "https://api.openai.com/v1"
    assert s.openai_max_retries == 2
    assert s.request_max_tokens == 4096


def test_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_WORKER_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_CLOUD_WORKER_OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("AGENT_CLOUD_WORKER_GRPC_PORT", "60000")
    s = WorkerSettings()
    assert s.openai_api_key == "sk-test"
    assert s.openai_base_url == "http://localhost:8000/v1"
    assert s.grpc_port == 60000
