from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pmc_agent.app_logging import get_logger, log_extra


logger = get_logger(__name__)


class Tool(Protocol):
    name: str
    description: str

    def run(self, **kwargs: Any) -> Any:
        ...


@dataclass
class ToolRegistry:
    tools: dict[str, Tool]

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            logger.error("tool not registered", extra=log_extra("tool_missing", tool_name=name))
            raise KeyError(f"Tool not registered: {name}")
        return self.tools[name]

    def run(self, name: str, **kwargs: Any) -> Any:
        logger.info("tool call started", extra=log_extra("tool_call_started", tool_name=name))
        result = self.get(name).run(**kwargs)
        result_size = len(result) if hasattr(result, "__len__") else 1
        logger.info("tool call completed", extra=log_extra("tool_call_completed", tool_name=name, result_size=result_size))
        return result
