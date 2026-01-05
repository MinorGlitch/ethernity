#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Callable

from ...crypto import parse_identities, parse_recipients


Parser = Callable[[str], list[str]]


def _load_key_material(inline: list[str], files: list[str], *, parser: Parser) -> list[str]:
    items = list(inline)
    for path in files:
        with open(path, "r", encoding="utf-8") as handle:
            items.extend(parser(handle.read()))
    return items


def _load_recipients(inline: list[str], files: list[str]) -> list[str]:
    return _load_key_material(inline, files, parser=parse_recipients)


def _load_identities(inline: list[str], files: list[str]) -> list[str]:
    return _load_key_material(inline, files, parser=parse_identities)
