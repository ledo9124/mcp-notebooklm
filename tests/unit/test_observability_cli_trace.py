"""Unit tests for root CLI trace binding."""

from __future__ import annotations

import json
import re

import click
from click.testing import CliRunner

from notebooklm.notebooklm_cli import cli
from notebooklm.observability.tracing import current_trace


def test_root_cli_binds_trace_context_for_subcommands():
    @click.command("trace-probe")
    @click.pass_context
    def trace_probe(ctx):
        trace = current_trace()
        click.echo(
            json.dumps(
                {
                    "ctx_trace_id": ctx.obj["trace_id"],
                    "bound_trace_id": None if trace is None else trace.trace_id,
                }
            )
        )

    cli.add_command(trace_probe)
    try:
        result = CliRunner().invoke(cli, ["trace-probe"])
    finally:
        cli.commands.pop("trace-probe", None)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ctx_trace_id"] == payload["bound_trace_id"]
    assert re.fullmatch(r"trc_[0-9A-HJKMNP-TV-Z]{26}", payload["ctx_trace_id"])
    assert current_trace() is None
