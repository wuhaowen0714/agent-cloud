import grpc
from agent_cloud_backend.turn.retry import RetryAction, RetryPolicy, classify


def _policy(**kw):
    base = dict(
        max_overflow_retries=2,
        max_transient_retries=3,
        max_total_attempts=6,
        backoff_base_seconds=0.5,
    )
    base.update(kw)
    return RetryPolicy(**base)


def test_classify():
    assert classify(grpc.StatusCode.RESOURCE_EXHAUSTED) == "overflow"
    assert classify(grpc.StatusCode.UNAVAILABLE) == "transient"
    assert classify(grpc.StatusCode.DEADLINE_EXCEEDED) == "transient"
    assert classify(grpc.StatusCode.INTERNAL) == "transient"
    assert classify(grpc.StatusCode.INVALID_ARGUMENT) == "fatal"
    assert classify(grpc.StatusCode.FAILED_PRECONDITION) == "fatal"


def test_backoff_is_exponential_and_capped():
    p = _policy(backoff_base_seconds=0.5)
    assert p.backoff_seconds(0) == 0.5
    assert p.backoff_seconds(1) == 1.0
    assert p.backoff_seconds(2) == 2.0
    assert p.backoff_seconds(10) == 8.0  # 封顶


def test_decide_overflow_retries_then_gives_up_at_cap():
    p = _policy(max_overflow_retries=2)
    c = grpc.StatusCode.RESOURCE_EXHAUSTED
    assert p.decide(c, overflow_used=0, transient_used=0, total_used=1) == RetryAction.COMPACT_RETRY
    assert p.decide(c, overflow_used=1, transient_used=0, total_used=2) == RetryAction.COMPACT_RETRY
    assert p.decide(c, overflow_used=2, transient_used=0, total_used=3) == RetryAction.GIVE_UP


def test_decide_transient_retries_then_gives_up_at_cap():
    p = _policy(max_transient_retries=3)
    c = grpc.StatusCode.UNAVAILABLE
    assert p.decide(c, overflow_used=0, transient_used=0, total_used=1) == RetryAction.BACKOFF_RETRY
    assert p.decide(c, overflow_used=0, transient_used=3, total_used=4) == RetryAction.GIVE_UP


def test_decide_fatal_never_retries():
    p = _policy()
    assert (
        p.decide(grpc.StatusCode.INVALID_ARGUMENT, overflow_used=0, transient_used=0, total_used=1)
        == RetryAction.GIVE_UP
    )


def test_decide_total_attempts_backstop():
    p = _policy(max_total_attempts=2)
    # 即便分类上限没到,total 兜底也会 GIVE_UP
    assert (
        p.decide(grpc.StatusCode.UNAVAILABLE, overflow_used=0, transient_used=0, total_used=2)
        == RetryAction.GIVE_UP
    )


def test_from_settings():
    from agent_cloud_backend.config import Settings

    p = RetryPolicy.from_settings(Settings(_env_file=None))
    assert p.max_overflow_retries == 2 and p.max_transient_retries == 3
    assert p.max_total_attempts == 6 and p.backoff_base_seconds == 0.5
