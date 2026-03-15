"""Unit tests for trace-aware JSON CLI output injection."""

from __future__ import annotations

import json
import re

import click
from click.testing import CliRunner

from notebooklm.cli.error_handler import handle_errors
from notebooklm.exceptions import ValidationError
from notebooklm.notebooklm_cli import cli


TRACE_ID_PATTERN = r"trc_[0-9A-HJKMNP-TV-Z]{26}"


def test_root_cli_injects_trace_id_into_json_success_output():
    @click.command("json-probe")
    def json_probe():
        click.echo(json.dumps({"ok": True, "value": 7}, indent=2))

    cli.add_command(json_probe)
    try:
        result = CliRunner().invoke(cli, ["json-probe"])
    finally:
        cli.commands.pop("json-probe", None)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["value"] == 7
    assert re.fullmatch(TRACE_ID_PATTERN, payload["trace_id"])


def test_root_cli_preserves_existing_trace_id_in_json_output():
    @click.command("json-existing-trace")
    def json_existing_trace():
        click.echo(json.dumps({"ok": True, "trace_id": "trc_existing"}, indent=2))

    cli.add_command(json_existing_trace)
    try:
        result = CliRunner().invoke(cli, ["json-existing-trace"])
    finally:
        cli.commands.pop("json-existing-trace", None)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["trace_id"] == "trc_existing"


def test_root_cli_injects_trace_id_into_json_error_output():
    @click.command("json-error-probe")
    def json_error_probe():
        with handle_errors(json_output=True):
            raise ValidationError("invalid payload")

    cli.add_command(json_error_probe)
    try:
        result = CliRunner().invoke(cli, ["json-error-probe"])
    finally:
        cli.commands.pop("json-error-probe", None)

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["route"]["intent"] == "LOCAL_METADATA"
    assert payload["route"]["mode"] == "handle_errors"
    assert payload["result"]["code"] == "VALIDATION_ERROR"
    assert "invalid payload" in payload["result"]["message"]
    assert re.fullmatch(TRACE_ID_PATTERN, payload["trace_id"])


def test_root_cli_leaves_plain_text_output_unchanged():
    @click.command("text-probe")
    def text_probe():
        click.echo("plain text output")

    cli.add_command(text_probe)
    try:
        result = CliRunner().invoke(cli, ["text-probe"])
    finally:
        cli.commands.pop("text-probe", None)

    assert result.exit_code == 0, result.output
    assert result.output == "plain text output\n"
