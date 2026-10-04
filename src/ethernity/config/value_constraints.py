"""Supported runtime choices and bounds shared by config parsing and validation."""

from __future__ import annotations

from ethernity.page_sizes import paper_size_names

PAGE_SIZES = paper_size_names()
QR_ERROR_LEVELS = ("L", "M", "Q", "H")
PAYLOAD_CODECS = ("auto", "raw", "gzip")
QR_PAYLOAD_CODECS = ("raw", "base64")
SIGNING_KEY_MODES = ("embedded", "sharded")


__all__ = [
    "PAGE_SIZES",
    "PAYLOAD_CODECS",
    "QR_ERROR_LEVELS",
    "QR_PAYLOAD_CODECS",
    "SIGNING_KEY_MODES",
]
