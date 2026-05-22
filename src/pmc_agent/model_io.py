from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any

from pmc_agent.app_logging import get_logger, log_extra


logger = get_logger(__name__)


def generate_time_id() -> str:
    """生成用于请求和模型交互文件的时间 ID。"""

    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def record_model_interaction(
    interaction_type: str,
    interaction_id: str,
    payload: dict[str, Any],
    output: Any | None = None,
    error: str | None = None,
    base_dir: str | Path = "logs/model_interactions",
) -> Path:
    """按一次用户对话记录模型输入输出。

    同一个 interaction_id 下的多次模型调用会追加到同一个文件，避免一次对话产生多个日志文件。
    """

    folder = Path(base_dir) / "conversations"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_safe_path_part(interaction_id)}.txt"

    entry = {
        "interaction_type": interaction_type,
        "created_at": datetime.now().isoformat(),
        "input": payload,
        "output": _to_jsonable(output),
        "error": error,
    }
    record = _read_existing_record(path, interaction_id)
    record["updated_at"] = datetime.now().isoformat()
    record["interactions"].append(entry)
    record["interaction_count"] = len(record["interactions"])
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "model interaction recorded",
        extra=log_extra("model_interaction_recorded", request_id=interaction_id, interaction_type=interaction_type, path=str(path)),
    )
    return path


def _read_existing_record(path: Path, interaction_id: str) -> dict[str, Any]:
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and isinstance(existing.get("interactions"), list):
                return existing
        except json.JSONDecodeError:
            pass
    return {
        "id": interaction_id,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "interaction_count": 0,
        "interactions": [],
    }


def _safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def _to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    return value
