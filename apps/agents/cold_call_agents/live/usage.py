"""Token usage recorded on the LLM clients so cost can be tracked later."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


class LLMError(Exception):
    """A failed model call. The writer catches this and falls back to a template."""


@dataclass
class TokenUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, input_tokens: object, output_tokens: object) -> None:
        i = input_tokens if isinstance(input_tokens, int) and input_tokens > 0 else 0
        o = output_tokens if isinstance(output_tokens, int) and output_tokens > 0 else 0
        with self._lock:
            self.calls += 1
            self.input_tokens += i
            self.output_tokens += o

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
