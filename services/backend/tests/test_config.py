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


def test_compaction_threshold_default_is_128k():
    s = Settings(_env_file=None)
    assert s.compaction_token_threshold == 128000
    assert s.compaction_token_thresholds == {}


def test_compaction_threshold_for_falls_back_to_default():
    s = Settings(_env_file=None)
    # 未配窗口、未配 override 的模型 → 回退全局默认。
    # (预设模型按「窗口 × 触发比例」解析,见 test_config_thresholds.py。)
    assert s.compaction_threshold_for("unknown-model") == 128000
    assert s.compaction_threshold_for("") == 128000


def test_compaction_threshold_for_uses_per_model_override():
    s = Settings(_env_file=None, compaction_token_thresholds={"DeepSeek-V4-Pro": 200000})
    assert s.compaction_threshold_for("DeepSeek-V4-Pro") == 200000  # 命中 override
    assert s.compaction_threshold_for("other-model") == 128000  # 未列出 → 默认


def test_compaction_thresholds_parsed_from_env_json(monkeypatch):
    # 预留接口:可经环境变量(JSON)按模型配阈值,无需改代码
    monkeypatch.setenv("AGENT_CLOUD_COMPACTION_TOKEN_THRESHOLDS", '{"m-small": 8000}')
    s = Settings()
    assert s.compaction_threshold_for("m-small") == 8000


def test_memory_settings_defaults():
    s = Settings(_env_file=None)
    assert s.memory_soft_chars == 2000
    assert s.memory_min_rounds == 10
    assert s.memory_idle_seconds == 1800
    assert s.memory_max_versions == 20
