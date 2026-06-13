from agent_cloud_worker.config import WorkerSettings


def test_defaults():
    # _env_file=None:忽略开发机本地可能存在的 .env(含真实凭据),测真正的代码默认值
    s = WorkerSettings(_env_file=None)
    assert s.grpc_port == 50052
    assert s.openai_base_url == "https://api.openai.com/v1"
    assert s.openai_timeout_seconds == 45.0  # 卡住更早重试(端点偶发首 token 卡顿)
    assert s.openai_max_retries == 3
    assert s.request_max_tokens == 32768
    assert s.max_iterations == 20  # 单回合 LLM↔工具往返上限
    assert s.timezone_offset_hours == 8.0  # 默认北京时区(注入"今天日期")
    assert s.network_region == "cn"  # 默认中国大陆:生产部署在阿里云境内
    assert s.web_search_api_key == ""  # 默认空 = 不暴露 web_search 工具
    assert s.web_search_endpoint == "https://www.sophnet.com/api/open-apis/moltbot/search/web"
    assert s.web_search_max_results == 8


def test_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_WORKER_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_CLOUD_WORKER_OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("AGENT_CLOUD_WORKER_GRPC_PORT", "60000")
    monkeypatch.setenv("AGENT_CLOUD_WORKER_MAX_ITERATIONS", "5")
    s = WorkerSettings()
    assert s.openai_api_key == "sk-test"
    assert s.openai_base_url == "http://localhost:8000/v1"
    assert s.grpc_port == 60000
    assert s.max_iterations == 5
