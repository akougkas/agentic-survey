from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

__all__ = ["MiraTool", "ToolDispatchError", "ToolRegistry"]

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class ToolDispatchError(RuntimeError):
    """Raised when a tool cannot be dispatched or its handler raises.

    The orchestrator catches this, formats the error back to Brain B as the
    tool-role message payload, and lets the model recover on the next
    iteration. It never swallows the error silently.
    """

    def __init__(self, tool: str, message: str, *, tool_args: dict[str, Any] | None = None) -> None:
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        self.tool_args = tool_args or {}


@dataclass(slots=True, frozen=True)
class MiraTool:
    """One callable tool Brain B may invoke via OpenAI-style tool calls."""

    name: str
    description: str
    parameters_schema: dict[str, Any]
    handler: ToolHandler

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


class ToolRegistry:
    """Ordered collection of MiraTools. Produces the OpenAI tool array and dispatches calls."""

    def __init__(self, tools: list[MiraTool] | None = None) -> None:
        self._tools: dict[str, MiraTool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: MiraTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def is_empty(self) -> bool:
        return not self._tools

    def openai_schema(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self._tools.values()]

    async def dispatch(self, name: str, arguments: str | dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolDispatchError(
                name,
                f"unknown tool; known: {sorted(self._tools)}",
            )
        parsed = arguments
        if isinstance(arguments, str):
            text = arguments.strip()
            if not text:
                parsed = {}
            else:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ToolDispatchError(
                        name,
                        f"arguments are not valid JSON: {exc}",
                        tool_args={"raw": arguments},
                    ) from exc
        if not isinstance(parsed, dict):
            raise ToolDispatchError(
                name,
                f"arguments must decode to an object, got {type(parsed).__name__}",
                tool_args={"raw": arguments},
            )
        try:
            return await tool.handler(parsed)
        except ToolDispatchError:
            raise
        except Exception as exc:
            raise ToolDispatchError(name, str(exc), tool_args=parsed) from exc
