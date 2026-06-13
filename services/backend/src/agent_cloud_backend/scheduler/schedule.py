from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

MIN_INTERVAL_SECONDS = 60
_GRACE_MIN = 120.0
_GRACE_MAX = 7200.0
_FRIENDLY = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class ScheduleError(ValueError):
    """排期参数非法(kind/expr/tz)。创建时抛出 → API 422 / agent 工具拒绝。"""


def _tz(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ScheduleError(f"未知时区:{tz!r}") from e


def _parse_interval_seconds(expr: str) -> int:
    e = expr.strip().lower()
    if e.isdigit():
        return int(e)
    if len(e) >= 2 and e[-1] in _FRIENDLY and e[:-1].isdigit():
        return int(e[:-1]) * _FRIENDLY[e[-1]]
    raise ScheduleError(f"interval 必须是正整数秒或如 30m/2h/1d:{expr!r}")


def _parse_once_utc(expr: str) -> datetime:
    try:
        dt = datetime.fromisoformat(expr.strip())
    except ValueError as e:
        raise ScheduleError(f"once 时间必须是 ISO8601:{expr!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def validate_and_normalize(kind: str, expr: str, tz: str) -> str:
    """校验并归一化 schedule_expr;非法抛 ScheduleError。返回入库用的规范化 expr。"""
    if kind == "once":
        return _parse_once_utc(expr).isoformat()
    if kind == "interval":
        secs = _parse_interval_seconds(expr)
        if secs < MIN_INTERVAL_SECONDS:
            raise ScheduleError(f"interval 最小 {MIN_INTERVAL_SECONDS}s:{secs}")
        return str(secs)
    if kind == "cron":
        _tz(tz)
        if not croniter.is_valid(expr.strip()):
            raise ScheduleError(f"非法 cron 表达式:{expr!r}")
        return expr.strip()
    raise ScheduleError(f"未知 schedule_kind:{kind!r}")


def first_run_at(kind: str, expr: str, tz: str, now: datetime) -> datetime | None:
    """创建/恢复时算首次 next_run(UTC)。once 过去也返回原时刻(由调用方决定是否立即跑)。"""
    if kind == "once":
        return _parse_once_utc(expr)
    if kind == "interval":
        return now + timedelta(seconds=int(expr))
    if kind == "cron":
        return croniter(expr, now.astimezone(_tz(tz))).get_next(datetime).astimezone(UTC)
    raise ScheduleError(f"未知 schedule_kind:{kind!r}")


def next_run_after(
    kind: str, expr: str, tz: str, *, prev: datetime, now: datetime
) -> datetime | None:
    """一次运行后推进 next_run。once→None;interval→保相位推进到 >now(跳过错过的整数周期);
    cron→now 之后的下一次。全部 UTC。"""
    if kind == "once":
        return None
    if kind == "interval":
        step = int(expr)
        elapsed = (now - prev).total_seconds()
        n = max(1, ceil(elapsed / step)) if elapsed > 0 else 1
        return prev + timedelta(seconds=n * step)
    if kind == "cron":
        return croniter(expr, now.astimezone(_tz(tz))).get_next(datetime).astimezone(UTC)
    raise ScheduleError(f"未知 schedule_kind:{kind!r}")


def grace_seconds(kind: str, expr: str, tz: str, prev: datetime) -> float:
    """陈旧判定容差:周期的一半,夹在 [120s, 2h]。once→0(迟到也跑,绝不快进跳过)。"""
    if kind == "once":
        return 0.0
    if kind == "interval":
        period = float(int(expr))
    elif kind == "cron":
        it = croniter(expr, prev.astimezone(_tz(tz)))
        a = it.get_next(datetime)
        b = it.get_next(datetime)
        period = (b - a).total_seconds()
    else:
        raise ScheduleError(f"未知 schedule_kind:{kind!r}")
    return min(_GRACE_MAX, max(_GRACE_MIN, period / 2))
