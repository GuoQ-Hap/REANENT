from __future__ import annotations

from pathlib import Path
import os

from pmc_agent.app_logging import get_logger, log_extra


logger = get_logger(__name__)

_DEFAULT_ENV_LOADED = False


def load_env_file(path: str | Path | None = None, override: bool = True) -> None:
    """Load simple KEY=VALUE pairs from .env."""

    global _DEFAULT_ENV_LOADED
    if _DEFAULT_ENV_LOADED and path is None and not override:
        return
    env_path = Path(path) if path else _find_project_env()
    if not env_path or not env_path.exists():
        if path is None:
            _DEFAULT_ENV_LOADED = True
        return

    loaded_count = 0
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = _clean_env_value(value.strip())
        loaded_count += 1
    if path is None:
        _DEFAULT_ENV_LOADED = True
    logger.info(
        "environment file loaded",
        extra=log_extra("env_file_loaded", path=str(env_path), loaded_count=loaded_count),
    )


def _find_project_env() -> Path | None:
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    return None


def _clean_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
