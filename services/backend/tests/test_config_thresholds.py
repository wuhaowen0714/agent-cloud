from agent_cloud_backend.config import Settings


def test_threshold_from_model_window_ratio():
    s = Settings()
    # 预设三模型:窗口 × 0.75
    assert s.compaction_threshold_for("DeepSeek-V4-Pro") == 750_000
    assert s.compaction_threshold_for("DeepSeek-V4-Flash") == 750_000
    assert s.compaction_threshold_for("GLM-5.1") == 150_000


def test_threshold_fallback_global_default():
    s = Settings()
    assert s.compaction_threshold_for("unknown-model") == s.compaction_token_threshold


def test_threshold_explicit_override_wins_over_window():
    s = Settings(compaction_token_thresholds={"DeepSeek-V4-Pro": 123})
    assert s.compaction_threshold_for("DeepSeek-V4-Pro") == 123
