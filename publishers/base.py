from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PublishResult:
    status: str            # posted | package_ready
    url: str | None = None


class PublishError(RuntimeError):
    pass
