from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from threading import RLock
from typing import Any, Callable, Iterator, TypeVar

from pmc_agent.app_logging import get_logger, log_extra


T = TypeVar("T")

logger = get_logger(__name__)
_FORCE_BOTTOM_TABLE_REFRESH: ContextVar[bool] = ContextVar("force_bottom_table_refresh", default=False)
_STAT_KEYS = ("hits", "misses", "refreshes", "writes", "stale_pruned")


@contextmanager
def bottom_table_force_refresh(enabled: bool = True) -> Iterator[None]:
    if not enabled:
        yield
        return
    token = _FORCE_BOTTOM_TABLE_REFRESH.set(True)
    try:
        yield
    finally:
        _FORCE_BOTTOM_TABLE_REFRESH.reset(token)


def bottom_table_refresh_requested() -> bool:
    return bool(_FORCE_BOTTOM_TABLE_REFRESH.get())


class DailyQueryCache:
    """Small process-local cache for read-only bottom-table queries.

    Entries are scoped by calendar day. Once the server date changes, old entries
    are ignored and pruned on the next write. Manual refresh uses a context var
    so one request can bypass cache without leaking to concurrent requests.
    """

    def __init__(self, today_fn: Callable[[], date] | None = None) -> None:
        self._today_fn = today_fn or date.today
        self._entries: dict[tuple[str, str, Any], Any] = {}
        self._stats: dict[str, dict[str, int]] = {}
        self._lock = RLock()

    def get_or_load(
        self,
        namespace: str,
        params: Any,
        loader: Callable[[], T],
        *,
        force_refresh: bool = False,
    ) -> T:
        cache_day = self._today_fn().isoformat()
        key = (cache_day, namespace, _freeze(params))
        refresh_requested = force_refresh or bottom_table_refresh_requested()
        if not refresh_requested:
            with self._lock:
                if key in self._entries:
                    self._bump(namespace, "hits")
                    logger.debug(
                        "bottom table cache hit",
                        extra=log_extra("bottom_table_cache_hit", cache_namespace=namespace, cache_day=cache_day),
                    )
                    return deepcopy(self._entries[key])
                self._bump(namespace, "misses")
            logger.debug(
                "bottom table cache miss",
                extra=log_extra("bottom_table_cache_miss", cache_namespace=namespace, cache_day=cache_day),
            )
        else:
            with self._lock:
                self._bump(namespace, "refreshes")
            logger.info(
                "bottom table cache refresh",
                extra=log_extra("bottom_table_cache_refresh", cache_namespace=namespace, cache_day=cache_day),
            )

        value = loader()
        with self._lock:
            pruned_by_namespace = self._prune_other_days(cache_day)
            for stale_namespace, pruned in pruned_by_namespace.items():
                self._bump(stale_namespace, "stale_pruned", pruned)
            self._entries[key] = deepcopy(value)
            self._bump(namespace, "writes")
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def reset_stats(self) -> None:
        with self._lock:
            self._stats.clear()

    def snapshot(self) -> dict[str, Any]:
        cache_day = self._today_fn().isoformat()
        with self._lock:
            entries_by_namespace: dict[str, int] = {}
            for _, namespace, _ in self._entries:
                entries_by_namespace[namespace] = entries_by_namespace.get(namespace, 0) + 1
            namespaces = sorted(set(entries_by_namespace) | set(self._stats))
            rows = []
            for namespace in namespaces:
                metrics = {key: int(self._stats.get(namespace, {}).get(key, 0)) for key in _STAT_KEYS}
                attempts = metrics["hits"] + metrics["misses"] + metrics["refreshes"]
                rows.append(
                    {
                        "namespace": namespace,
                        "entries": entries_by_namespace.get(namespace, 0),
                        **metrics,
                        "hit_rate": round(metrics["hits"] / attempts, 4) if attempts else 0,
                    }
                )
            return {
                "cache_day": cache_day,
                "entry_count": len(self._entries),
                "namespace_count": len(rows),
                "namespaces": rows,
            }

    def _bump(self, namespace: str, metric: str, amount: int = 1) -> None:
        stats = self._stats.setdefault(namespace, {key: 0 for key in _STAT_KEYS})
        stats[metric] = stats.get(metric, 0) + amount

    def _prune_other_days(self, cache_day: str) -> dict[str, int]:
        stale_keys = [key for key in self._entries if key[0] != cache_day]
        pruned_by_namespace: dict[str, int] = {}
        for key in stale_keys:
            pruned_by_namespace[key[1]] = pruned_by_namespace.get(key[1], 0) + 1
            self._entries.pop(key, None)
        return pruned_by_namespace


def _freeze(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _freeze(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


BOTTOM_TABLE_QUERY_CACHE = DailyQueryCache()
