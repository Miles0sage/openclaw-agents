"""
Response Cache for OpenClaw Gateway
In-memory LRU cache with TTL for reducing redundant API calls
Target: 15%+ cost reduction on repeated/similar queries
"""

import hashlib
import time
import json
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from collections import OrderedDict
from threading import Lock

logger = logging.getLogger("response_cache")


@dataclass
class CacheEntry:
    """Single cache entry with metadata"""
    response: str
    agent_id: str
    model: str
    provider: str
    tokens_saved: int
    created_at: float
    ttl_seconds: float
    hit_count: int = 0
    last_accessed: float = 0.0

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


class ResponseCache:
    """
    LRU response cache with TTL expiration

    Features:
    - Configurable TTL (default 30s for chat, 300s for routing)
    - LRU eviction when max size reached
    - Thread-safe operations
    - Cache key normalization (strips whitespace, lowercases)
    - Statistics tracking (hits, misses, savings)
    """

    def __init__(self, default_ttl: float = 30, max_entries: int = 1000):
        self.default_ttl = default_ttl
        self.max_entries = max_entries
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = Lock()

        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "total_tokens_saved": 0,
            "total_cost_saved_usd": 0.0,
            "entries_expired": 0,
        }

    def _normalize_key(self, query: str, agent_id: str = "", session_key: str = "") -> str:
        """Generate cache key from query + agent context"""
        normalized = " ".join(query.lower().split())
        key_string = f"{normalized}|{agent_id}|{session_key}"
        return hashlib.sha256(key_string.encode()).hexdigest()

    def get(self, query: str, agent_id: str = "", session_key: str = "") -> Optional[CacheEntry]:
        """Look up cached response. Returns CacheEntry if found and not expired."""
        key = self._normalize_key(query, agent_id, session_key)

        with self._lock:
            if key not in self._cache:
                self.stats["misses"] += 1
                return None

            entry = self._cache[key]

            if entry.is_expired:
                del self._cache[key]
                self.stats["entries_expired"] += 1
                self.stats["misses"] += 1
                return None

            entry.hit_count += 1
            entry.last_accessed = time.time()
            self.stats["hits"] += 1
            self.stats["total_tokens_saved"] += entry.tokens_saved

            # Estimate cost saved (avg $0.003/1K output tokens across models)
            self.stats["total_cost_saved_usd"] += entry.tokens_saved * 0.003 / 1000

            # Move to end (most recently used)
            self._cache.move_to_end(key)

            logger.info(f"Cache HIT for agent={agent_id} (saved {entry.tokens_saved} tokens)")
            return entry

    def put(self, query: str, response: str, agent_id: str, model: str,
            provider: str, tokens_output: int, ttl: Optional[float] = None,
            session_key: str = "") -> None:
        """Store response in cache"""
        key = self._normalize_key(query, agent_id, session_key)
        ttl = ttl or self.default_ttl

        with self._lock:
            while len(self._cache) >= self.max_entries:
                self._cache.popitem(last=False)
                self.stats["evictions"] += 1

            self._cache[key] = CacheEntry(
                response=response,
                agent_id=agent_id,
                model=model,
                provider=provider,
                tokens_saved=tokens_output,
                created_at=time.time(),
                ttl_seconds=ttl,
                last_accessed=time.time()
            )

    def invalidate(self, query: str = None, agent_id: str = None) -> int:
        """Invalidate cache entries. No args = clear all."""
        count = 0
        with self._lock:
            if query:
                key = self._normalize_key(query, agent_id or "")
                if key in self._cache:
                    del self._cache[key]
                    count = 1
            elif agent_id:
                keys_to_remove = [k for k, v in self._cache.items() if v.agent_id == agent_id]
                for k in keys_to_remove:
                    del self._cache[k]
                count = len(keys_to_remove)
            else:
                count = len(self._cache)
                self._cache.clear()

        logger.info(f"Invalidated {count} cache entries")
        return count

    def cleanup_expired(self) -> int:
        """Remove all expired entries"""
        count = 0
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired]
            for k in expired_keys:
                del self._cache[k]
                count += 1
            self.stats["entries_expired"] += count

        if count > 0:
            logger.info(f"Cleaned up {count} expired cache entries")
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            total = self.stats["hits"] + self.stats["misses"]
            hit_rate = self.stats["hits"] / total if total > 0 else 0

            return {
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "hit_rate": round(hit_rate, 4),
                "hit_rate_percent": f"{hit_rate * 100:.1f}%",
                "total_entries": len(self._cache),
                "max_entries": self.max_entries,
                "evictions": self.stats["evictions"],
                "expired": self.stats["entries_expired"],
                "total_tokens_saved": self.stats["total_tokens_saved"],
                "total_cost_saved_usd": round(self.stats["total_cost_saved_usd"], 4),
                "default_ttl_seconds": self.default_ttl,
            }


# Singleton
_cache_instance: Optional[ResponseCache] = None

def init_response_cache(default_ttl: float = 30, max_entries: int = 1000) -> ResponseCache:
    """Initialize the global response cache"""
    global _cache_instance
    _cache_instance = ResponseCache(default_ttl=default_ttl, max_entries=max_entries)
    logger.info(f"Response cache initialized (TTL={default_ttl}s, max={max_entries})")
    return _cache_instance

def get_response_cache() -> Optional[ResponseCache]:
    """Get the global response cache instance"""
    return _cache_instance
