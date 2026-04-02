import time
from abc import ABC, abstractmethod
from typing import Dict, Set, Tuple


class RateLimitStorage(ABC):

    @abstractmethod
    async def hit(self, key: str, ttl_seconds: int = 60) -> int:
        pass

    @abstractmethod
    async def get(self, key: str) -> int:
        pass

    @abstractmethod
    async def block_ip(self, ip: str, duration_seconds: int) -> None:
        pass

    @abstractmethod
    async def is_blocked(self, ip: str) -> bool:
        pass


class MemoryRateLimitStorage(RateLimitStorage):
    def __init__(self):
        self._storage: Dict[str, Tuple[int, float]] = {}
        self._blocked_ips: Dict[str, float] = {}

    async def hit(self, key: str, ttl_seconds: int = 60) -> int:
        now = time.time()
        self._cleanup(now)

        if key in self._storage:
            count, expires_at = self._storage[key]
            if now > expires_at:
                self._storage[key] = (1, now + ttl_seconds)
                return 1
            else:
                new_count = count + 1
                self._storage[key] = (new_count, expires_at)
                return new_count
        else:
            self._storage[key] = (1, now + ttl_seconds)
            return 1

    async def get(self, key: str) -> int:
        now = time.time()
        if key in self._storage:
            count, expires_at = self._storage[key]
            if now > expires_at:
                return 0
            return count
        return 0

    async def block_ip(self, ip: str, duration_seconds: int) -> None:
        self._blocked_ips[ip] = time.time() + duration_seconds

    async def is_blocked(self, ip: str) -> bool:
        if ip not in self._blocked_ips:
            return False
        if time.time() > self._blocked_ips[ip]:
            del self._blocked_ips[ip]
            return False
        return True

    def _cleanup(self, now: float):
        keys_to_delete = [k for k, v in self._storage.items() if now > v[1]]
        for k in keys_to_delete:
            del self._storage[k]
        blocked_to_delete = [k for k, v in self._blocked_ips.items() if now > v]
        for k in blocked_to_delete:
            del self._blocked_ips[k]
