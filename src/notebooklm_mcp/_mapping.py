"""String/enum mapping helpers for notebooklm-mcp tools.

This module centralizes conversion between MCP-facing string parameters and
NotebookLM enum values.
"""

from __future__ import annotations

import inspect
import re
from enum import Enum
from functools import lru_cache
from typing import TypeVar, cast

import notebooklm.rpc.types as rpc_types
import notebooklm.types as core_types
from notebooklm.exceptions import ValidationError

E = TypeVar("E", bound=Enum)

_TOKEN_SPLIT_RE = re.compile(r"[\s\-_]+")


def _collect_supported_enums() -> tuple[type[Enum], ...]:
    """Collect enum classes declared in notebooklm.types and rpc.types."""
    seen: set[type[Enum]] = set()
    classes: list[type[Enum]] = []

    for module in (core_types, rpc_types):
        for obj in vars(module).values():
            if not inspect.isclass(obj):
                continue
            if not issubclass(obj, Enum):
                continue
            if obj.__module__ != module.__name__:
                continue
            if obj in seen:
                continue
            seen.add(obj)
            classes.append(obj)

    classes.sort(key=lambda enum_cls: (enum_cls.__module__, enum_cls.__name__))
    return tuple(classes)


SUPPORTED_ENUMS: tuple[type[Enum], ...] = _collect_supported_enums()


def _normalize_token(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    return _TOKEN_SPLIT_RE.sub("_", stripped.casefold())


def _canonical_name(member_name: str) -> str:
    return member_name.casefold().replace("_", "-")


@lru_cache(maxsize=None)
def _enum_lookup(enum_class: type[Enum]) -> dict[str, Enum]:
    lookup: dict[str, Enum] = {}
    for name, member in enum_class.__members__.items():
        lookup[_normalize_token(name)] = member
        lookup[_normalize_token(_canonical_name(name))] = member

        if isinstance(member.value, str):
            lookup[_normalize_token(member.value)] = member
        else:
            lookup[str(member.value)] = member
    return lookup


@lru_cache(maxsize=None)
def valid_enum_values(enum_class: type[Enum]) -> tuple[str, ...]:
    """Return normalized user-facing strings accepted by ``map_to_enum``."""
    values = {_canonical_name(name) for name in enum_class.__members__}
    return tuple(sorted(values))


def _validation_error(enum_class: type[Enum], field_name: str, value: object) -> ValidationError:
    valid = ", ".join(valid_enum_values(enum_class))
    return ValidationError(f"{field_name} must be one of: {valid}. Got: {value!r}")


def map_to_enum(value: str | int | E, enum_class: type[E], *, field_name: str = "value") -> E:
    """Convert string/int input into a concrete enum member.

    Accepted inputs:
    - Enum member of ``enum_class`` (returned as-is)
    - String name/value (case-insensitive, dash/underscore tolerant)
    - Integer value for int-backed enums
    """
    if isinstance(value, enum_class):
        return value

    if isinstance(value, int) and not isinstance(value, bool):
        try:
            return enum_class(value)
        except ValueError as exc:
            raise _validation_error(enum_class, field_name, value) from exc

    if not isinstance(value, str):
        raise _validation_error(enum_class, field_name, value)

    normalized = _normalize_token(value)
    if not normalized:
        raise _validation_error(enum_class, field_name, value)

    mapped = _enum_lookup(enum_class).get(normalized)
    if mapped is None:
        raise _validation_error(enum_class, field_name, value)

    return cast(E, mapped)


def map_from_enum(value: E | str | int, enum_class: type[E] | None = None) -> str:
    """Convert enum/int/string input into canonical MCP string form."""
    if enum_class is None:
        if not isinstance(value, Enum):
            raise ValidationError("enum_class is required when value is not an enum member")
        member = value
    else:
        member = map_to_enum(value, enum_class)

    return _canonical_name(member.name)


__all__ = [
    "SUPPORTED_ENUMS",
    "map_from_enum",
    "map_to_enum",
    "valid_enum_values",
]
