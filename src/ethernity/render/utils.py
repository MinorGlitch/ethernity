#!/usr/bin/env python3
from __future__ import annotations


def int_value(value: object, *, default: int) -> int:
    """Coerce a value to int with fallback to default."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def float_value(value: object, *, default: float) -> float:
    """Coerce a value to float with fallback to default."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default
