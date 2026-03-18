"""Shared utilities for the multi-agent event planner."""

from __future__ import annotations


def get_text(content) -> str:
    """Extract plain text from a message content field.

    LangGraph messages can have content as either a plain string or a list
    of content blocks (e.g. [{"type": "text", "text": "hello"}]).
    This function normalizes both to a plain string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts)
    return str(content)
