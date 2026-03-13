from __future__ import annotations

from ethernity.encoding.framing import FrameType

from .bootstrap import SRC_ROOT as _SRC_ROOT  # noqa: F401

MODE_AUTO = "auto"
MODE_PAYLOADS = "payload"
MODE_FALLBACK = "fallback"

DEFAULT_FALLBACK_GROUP_SIZE = 4
DEFAULT_FALLBACK_LINE_LENGTH = 80
TEXT_PREVIEW_LIMIT = 8192
RAW_PREVIEW_LIMIT = 96

FRAME_TYPE_LABELS = {
    int(FrameType.MAIN_DOCUMENT): "MAIN_DOCUMENT",
    int(FrameType.AUTH): "AUTH",
    int(FrameType.KEY_DOCUMENT): "KEY_DOCUMENT",
}

SCAN_SUFFIXES = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".webp",
}

__all__ = [
    "DEFAULT_FALLBACK_GROUP_SIZE",
    "DEFAULT_FALLBACK_LINE_LENGTH",
    "FRAME_TYPE_LABELS",
    "MODE_AUTO",
    "MODE_FALLBACK",
    "MODE_PAYLOADS",
    "RAW_PREVIEW_LIMIT",
    "SCAN_SUFFIXES",
    "TEXT_PREVIEW_LIMIT",
]
