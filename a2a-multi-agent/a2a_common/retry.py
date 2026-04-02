from __future__ import annotations

import asyncio
import functools
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Set, Type, TypeVar, Union

import httpx

from a2a_common.logging import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

@dataclass
class RetryPolicy:

    max_retries: int = 3
    base_delay: float = 1.0  
    max_delay: float = 30.0  
    exponential_base: float = 2.0
    jitter: bool = True  

    retryable_exceptions: Set[Type[Exception]] = field(
        default_factory=lambda: {
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.ConnectTimeout,
            ConnectionError,
            TimeoutError,
        }
    )

    retryable_status_codes: Set[int] = field(
        default_factory=lambda: {408, 429, 500, 502, 503, 504}
    )

    def calculate_delay(self, attempt: int) -> float:
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)

        if self.jitter:
            jitter_range = delay * 0.25
            delay = delay + random.uniform(-jitter_range, jitter_range)

        return max(0, delay)

DEFAULT_RETRY_POLICY = RetryPolicy(
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
)

def is_retryable(
    exc: Exception,
    policy: Optional[RetryPolicy] = None,
) -> bool:
    policy = policy or DEFAULT_RETRY_POLICY

    for exc_type in policy.retryable_exceptions:
        if isinstance(exc, exc_type):
            return True

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in policy.retryable_status_codes

    return False

def retry_with_backoff(
    policy: Optional[RetryPolicy] = None,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> Callable[[F], F]:
    policy = policy or DEFAULT_RETRY_POLICY

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None

            for attempt in range(policy.max_retries + 1):
                try:
                    return await func(*args, **kwargs)

                except Exception as exc:
                    last_exception = exc

                    if not is_retryable(exc, policy):
                        logger.warning(
                            "Non-retryable exception in %s: %s",
                            func.__name__,
                            exc,
                        )
                        raise

                    if attempt >= policy.max_retries:
                        logger.error(
                            "Max retries (%d) exceeded for %s: %s",
                            policy.max_retries,
                            func.__name__,
                            exc,
                        )
                        raise

                    delay = policy.calculate_delay(attempt)
                    logger.info(
                        "Retry %d/%d for %s after %.2fs: %s",
                        attempt + 1,
                        policy.max_retries,
                        func.__name__,
                        delay,
                        exc,
                    )

                    if on_retry:
                        on_retry(attempt, exc)

                    await asyncio.sleep(delay)

            if last_exception:
                raise last_exception

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            import time

            last_exception: Optional[Exception] = None

            for attempt in range(policy.max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as exc:
                    last_exception = exc

                    if not is_retryable(exc, policy):
                        raise

                    if attempt >= policy.max_retries:
                        raise

                    delay = policy.calculate_delay(attempt)
                    logger.info(
                        "Retry %d/%d for %s after %.2fs: %s",
                        attempt + 1,
                        policy.max_retries,
                        func.__name__,
                        delay,
                        exc,
                    )

                    if on_retry:
                        on_retry(attempt, exc)

                    time.sleep(delay)

            if last_exception:
                raise last_exception

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  
        return sync_wrapper  

    return decorator

class RetryExhaustedError(Exception):

    def __init__(
        self,
        message: str,
        attempts: int,
        last_exception: Optional[Exception] = None,
    ):
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(f"{message} after {attempts} attempts")
