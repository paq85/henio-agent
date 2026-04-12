"""Minimal built-in memory provider shim.

The new memory stack still documents a built-in provider, and several tests
import ``BuiltinMemoryProvider`` directly. The runtime no longer wires a
separate built-in provider object, but keeping this tiny no-op implementation
preserves that public import path and lets ``MemoryManager`` exercise its
"builtin + one external" registration rules.
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent.memory_provider import MemoryProvider


class BuiltinMemoryProvider(MemoryProvider):
    """No-op built-in provider used for compatibility and tests."""

    @property
    def name(self) -> str:
        return "builtin"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        del session_id, kwargs

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        del user_content, assistant_content, session_id

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return []

    def shutdown(self) -> None:
        return None