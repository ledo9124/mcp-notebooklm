"""Focused tests for the structured-command router guard."""

from notebooklm.router.structured import (
    StructuredCommandMatch,
    is_structured_command_request,
    match_structured_command,
)


def test_match_structured_command_accepts_root_command_with_prefix():
    match = match_structured_command('notebooklm ask "hello"')

    assert match == StructuredCommandMatch(
        command_path=("ask",),
        argv=("ask", "hello"),
        arguments=("hello",),
    )


def test_match_structured_command_accepts_grouped_command():
    match = match_structured_command("generate report --format study-guide")

    assert match == StructuredCommandMatch(
        command_path=("generate", "report"),
        argv=("generate", "report", "--format", "study-guide"),
        arguments=("--format", "study-guide"),
    )


def test_match_structured_command_accepts_grouped_metadata_command():
    match = match_structured_command("notebook list --refresh")

    assert match == StructuredCommandMatch(
        command_path=("notebook", "list"),
        argv=("notebook", "list", "--refresh"),
        arguments=("--refresh",),
    )


def test_match_structured_command_rejects_lookalike_natural_language_phrase():
    assert match_structured_command("list notebooks") is None


def test_match_structured_command_rejects_natural_language_summary_request():
    assert match_structured_command("summarize the current notebook") is None


def test_match_structured_command_rejects_group_without_leaf():
    assert match_structured_command("generate") is None


def test_match_structured_command_accepts_route_explain_command():
    match = match_structured_command('route explain "request"')

    assert match == StructuredCommandMatch(
        command_path=("route", "explain"),
        argv=("route", "explain", "request"),
        arguments=("request",),
    )


def test_match_structured_command_accepts_route_dry_run_command():
    match = match_structured_command('route "request" --dry-run')

    assert match == StructuredCommandMatch(
        command_path=("route",),
        argv=("route", "request", "--dry-run"),
        arguments=("request", "--dry-run"),
    )


def test_is_structured_command_request_reflects_match_result():
    assert is_structured_command_request("list --json") is True
    assert is_structured_command_request('route "request" --dry-run') is True
    assert is_structured_command_request('route explain "request"') is True
    assert is_structured_command_request("show me cached notebooks") is False
