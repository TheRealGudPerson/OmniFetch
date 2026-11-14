"""Shared models and URL validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass
class ProbeResult:
    engine: str
    status: str
    supported: bool
    confidence: int
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DownloadResult:
    engine: str
    success: bool
    message: str
    output_path: str | None = None


def validate_url(value: str) -> str:
    """Accept only absolute HTTP(S) URLs with a hostname."""
    cleaned = value.strip()
    parsed = urlsplit(cleaned)

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only http:// and https:// URLs are supported.")
    if not parsed.hostname:
        raise ValueError("The URL must include a hostname.")
    if any(char.isspace() for char in cleaned):
        raise ValueError("The URL cannot contain unescaped whitespace.")

    return cleaned


def safe_filename(value: str, fallback: str = "omnifetch-download") -> str:
    """Turn an untrusted title or header value into a safe single filename."""
    import re
    import unicodedata

    name = unicodedata.normalize("NFKC", str(value or "")).strip()
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name or name in {".", ".."}:
        name = fallback
    return name[:180]
