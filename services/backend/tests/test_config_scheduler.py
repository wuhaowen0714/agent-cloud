from agent_cloud_backend.config import Settings


def test_scheduler_defaults():
    s = Settings(_env_file=None)
    assert s.scheduler_enabled is True
    assert s.scheduler_poll_interval_seconds == 30
    assert s.scheduler_batch_size == 10
    assert s.scheduler_run_lease_seconds == 900
    assert s.scheduler_max_concurrent_runs == 4


def test_scheduler_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("AGENT_CLOUD_SCHEDULER_POLL_INTERVAL_SECONDS", "5")
    s = Settings()
    assert s.scheduler_enabled is False
    assert s.scheduler_poll_interval_seconds == 5
