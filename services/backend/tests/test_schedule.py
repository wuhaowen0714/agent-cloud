from datetime import UTC, datetime, timedelta

import pytest
from agent_cloud_backend.scheduler import schedule
from agent_cloud_backend.scheduler.schedule import ScheduleError

NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)


def test_validate_once_normalizes_to_utc():
    out = schedule.validate_and_normalize("once", "2026-06-14T09:00:00+08:00", "Asia/Shanghai")
    assert out == "2026-06-14T01:00:00+00:00"  # +08 → UTC


def test_validate_interval_friendly_and_floor():
    assert schedule.validate_and_normalize("interval", "30m", "UTC") == "1800"
    assert schedule.validate_and_normalize("interval", "120", "UTC") == "120"
    with pytest.raises(ScheduleError):
        schedule.validate_and_normalize("interval", "30", "UTC")  # < 60s


def test_validate_cron_and_tz():
    assert schedule.validate_and_normalize("cron", "0 9 * * *", "Asia/Shanghai") == "0 9 * * *"
    with pytest.raises(ScheduleError):
        schedule.validate_and_normalize("cron", "not a cron", "UTC")
    with pytest.raises(ScheduleError):
        schedule.validate_and_normalize("cron", "0 9 * * *", "Mars/Phobos")


def test_validate_unknown_kind():
    with pytest.raises(ScheduleError):
        schedule.validate_and_normalize("weekly", "x", "UTC")


def test_first_run_at():
    assert schedule.first_run_at("interval", "1800", "UTC", NOW) == NOW + timedelta(seconds=1800)
    assert schedule.first_run_at("once", "2026-06-14T01:00:00+00:00", "UTC", NOW) == datetime(
        2026, 6, 14, 1, 0, tzinfo=UTC
    )
    # cron 0 9 * * * in +08 → 次日 09:00 +08 = 01:00 UTC
    nxt = schedule.first_run_at("cron", "0 9 * * *", "Asia/Shanghai", NOW)
    assert nxt == datetime(2026, 6, 14, 1, 0, tzinfo=UTC)


def test_next_run_after_once_is_none():
    assert schedule.next_run_after("once", "x", "UTC", prev=NOW, now=NOW) is None


def test_next_run_after_interval_preserves_phase_and_skips_missed():
    prev = NOW
    # 只过了一点 → 推进一个周期
    n1 = schedule.next_run_after(
        "interval", "600", "UTC", prev=prev, now=NOW + timedelta(seconds=10)
    )
    assert n1 == prev + timedelta(seconds=600)
    # 错过 3 个周期(停机)→ 直接跳到第 4 个相位点,不补积压
    n2 = schedule.next_run_after(
        "interval", "600", "UTC", prev=prev, now=NOW + timedelta(seconds=1850)
    )
    assert n2 == prev + timedelta(seconds=4 * 600)


def test_grace_seconds_clamped():
    assert schedule.grace_seconds("interval", "600", "UTC", NOW) == 300.0  # 600/2
    assert schedule.grace_seconds("interval", "120", "UTC", NOW) == 120.0  # 60 夹到下限 120
    assert schedule.grace_seconds("interval", "86400", "UTC", NOW) == 7200.0  # 夹到上限 2h
    assert schedule.grace_seconds("once", "x", "UTC", NOW) == 0.0  # once 永不快进跳过
