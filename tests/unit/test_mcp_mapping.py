"""Unit tests for notebooklm_mcp._mapping."""

from __future__ import annotations

import inspect
from enum import Enum

import notebooklm.rpc.types as rpc_types
import notebooklm.types as core_types
import pytest

from notebooklm.exceptions import ValidationError
from notebooklm.rpc.types import AudioFormat, ChatGoal, QuizQuantity, SourceStatus
from notebooklm_mcp._mapping import SUPPORTED_ENUMS, map_from_enum, map_to_enum, valid_enum_values


def _discover_enum_classes() -> tuple[type[Enum], ...]:
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


def test_supported_enums_matches_types_and_rpc_modules() -> None:
    assert SUPPORTED_ENUMS == _discover_enum_classes()


@pytest.mark.parametrize("enum_class", SUPPORTED_ENUMS)
def test_map_to_enum_accepts_names_values_and_aliases(enum_class: type[Enum]) -> None:
    for name, member in enum_class.__members__.items():
        assert map_to_enum(name, enum_class) is member
        assert map_to_enum(name.lower(), enum_class) is member

        if "_" in name:
            assert map_to_enum(name.lower().replace("_", "-"), enum_class) is member

        if isinstance(member.value, str):
            assert map_to_enum(member.value, enum_class) is member
            assert map_to_enum(member.value.upper(), enum_class) is member
            if "_" in member.value:
                assert map_to_enum(member.value.replace("_", "-"), enum_class) is member
        else:
            assert map_to_enum(str(member.value), enum_class) is member
            assert map_to_enum(member.value, enum_class) is member


@pytest.mark.parametrize("enum_class", SUPPORTED_ENUMS)
def test_map_from_enum_roundtrip_for_unique_members(enum_class: type[Enum]) -> None:
    for member in enum_class:
        as_text = map_from_enum(member)
        assert map_to_enum(as_text, enum_class) is member
        assert as_text == member.name.lower().replace("_", "-")


def test_dash_underscore_and_whitespace_normalization() -> None:
    assert map_to_enum(" Deep-Dive ", AudioFormat) is AudioFormat.DEEP_DIVE


def test_alias_name_maps_to_canonical_member() -> None:
    assert map_to_enum("more", QuizQuantity) is QuizQuantity.STANDARD
    assert map_from_enum(QuizQuantity.MORE) == "standard"


def test_map_to_enum_unknown_value_includes_valid_values() -> None:
    with pytest.raises(ValidationError) as exc_info:
        map_to_enum("invalid", ChatGoal, field_name="goal")

    message = str(exc_info.value)
    assert "goal must be one of:" in message
    assert "default" in message
    assert "learning-guide" in message


def test_map_from_enum_requires_class_for_raw_values() -> None:
    with pytest.raises(ValidationError, match="enum_class is required"):
        map_from_enum(1)  # type: ignore[arg-type]


def test_map_from_enum_accepts_raw_when_enum_class_provided() -> None:
    assert map_from_enum(1, SourceStatus) == "processing"


def test_valid_enum_values_are_sorted_and_include_aliases() -> None:
    values = valid_enum_values(QuizQuantity)
    assert values == tuple(sorted(values))
    assert "fewer" in values
    assert "standard" in values
    assert "more" in values
