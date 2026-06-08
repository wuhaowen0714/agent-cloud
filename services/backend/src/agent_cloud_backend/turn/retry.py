from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import grpc

_TRANSIENT = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.INTERNAL,
}
_MAX_BACKOFF_SECONDS = 8.0


class RetryAction(Enum):
    COMPACT_RETRY = "compact_retry"  # 超窗:先 force_compact 再重试(进展门控在调用方)
    BACKOFF_RETRY = "backoff_retry"  # 瞬时:退避后重试同一请求
    GIVE_UP = "give_up"


def classify(code: grpc.StatusCode) -> str:
    if code == grpc.StatusCode.RESOURCE_EXHAUSTED:
        return "overflow"
    if code in _TRANSIENT:
        return "transient"
    return "fatal"


@dataclass
class RetryPolicy:
    max_overflow_retries: int
    max_transient_retries: int
    max_total_attempts: int
    backoff_base_seconds: float

    @classmethod
    def from_settings(cls, settings) -> RetryPolicy:
        return cls(
            max_overflow_retries=settings.turn_max_overflow_retries,
            max_transient_retries=settings.turn_max_transient_retries,
            max_total_attempts=settings.turn_max_total_attempts,
            backoff_base_seconds=settings.turn_retry_backoff_base_seconds,
        )

    def backoff_seconds(self, transient_index: int) -> float:
        return min(self.backoff_base_seconds * (2**transient_index), _MAX_BACKOFF_SECONDS)

    def decide(
        self,
        code: grpc.StatusCode,
        *,
        overflow_used: int,
        transient_used: int,
        total_used: int,
    ) -> RetryAction:
        # 进展门控(force_compact 是否有进展)留给调用方:本函数只看 code + 计数。
        if total_used >= self.max_total_attempts:
            return RetryAction.GIVE_UP
        kind = classify(code)
        if kind == "overflow":
            return (
                RetryAction.COMPACT_RETRY
                if overflow_used < self.max_overflow_retries
                else RetryAction.GIVE_UP
            )
        if kind == "transient":
            return (
                RetryAction.BACKOFF_RETRY
                if transient_used < self.max_transient_retries
                else RetryAction.GIVE_UP
            )
        return RetryAction.GIVE_UP
