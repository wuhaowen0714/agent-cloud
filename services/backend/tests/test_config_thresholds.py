from agent_cloud_backend.config import Settings

# _env_file=None:忽略开发机本地 .env,测真正的代码默认值(与 test_config.py 同约定)


def test_threshold_from_model_window_ratio():
    s = Settings(_env_file=None)
    # 预设三模型:窗口 × 0.75
    assert s.compaction_threshold_for("DeepSeek-V4-Pro") == 750_000
    assert s.compaction_threshold_for("DeepSeek-V4-Flash") == 750_000
    assert s.compaction_threshold_for("GLM-5.1") == 150_000


def test_threshold_fallback_global_default():
    s = Settings(_env_file=None)
    assert s.compaction_threshold_for("unknown-model") == s.compaction_token_threshold


def test_threshold_explicit_override_wins_over_window():
    s = Settings(_env_file=None, compaction_token_thresholds={"DeepSeek-V4-Pro": 123})
    assert s.compaction_threshold_for("DeepSeek-V4-Pro") == 123
