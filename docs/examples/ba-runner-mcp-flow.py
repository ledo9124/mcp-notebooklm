#!/usr/bin/env python3
"""Runnable stdio MCP example for the BA runner surface.

Legacy/frozen note:
    This example is retained as historical reference while the mainline branch
    is focused on the CLI/SDK MVP and does not actively ship notebooklm_mcp.

This script demonstrates the intended BA MCP happy path:
1. Start `notebooklm_mcp` over stdio
2. Create or reuse a NotebookLM notebook
3. Run `ba.run_pipeline` with typed inline BA sources
4. Inspect the persisted run via `ba.status`

Prerequisites:
    pip install "notebooklm-py[mcp,browser]"
    playwright install chromium
    notebooklm login

Usage:
    python docs/examples/ba-runner-mcp-flow.py
    python docs/examples/ba-runner-mcp-flow.py --notebook-id nb-123
    python docs/examples/ba-runner-mcp-flow.py --output-dir ./tmp/ba-demo

Notes:
    - The script leaves the notebook in place for review.
    - The output bundle is written under <output_dir>/docs/features/<feature_key>/.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import textwrap
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _demo_sources() -> list[dict[str, Any]]:
    requirements = textwrap.dedent(
        """
        # Customer onboarding

        Users can create an account with email, full name, password, and plan selection.
        The onboarding screen validates required fields inline and blocks submission until valid.
        After submit, the UI shows a success state and routes the user to the welcome checklist.
        Duplicate emails must surface a clear error message without losing the entered form data.
        """
    ).strip()

    contract = textwrap.dedent(
        """
        POST /api/customers
        Request body:
        - email: string
        - fullName: string
        - password: string
        - planId: string

        Responses:
        - 201 Created: { customerId, status, welcomeChecklistId }
        - 409 Conflict: { code, message } for duplicate email
        - 422 Unprocessable Entity: field-level validation errors
        """
    ).strip()

    glossary = textwrap.dedent(
        """
        Glossary:
        - customer: a signed-up end user who owns a subscription
        - welcome checklist: the first-run onboarding task list shown after account creation
        - plan: the selected subscription tier at signup
        """
    ).strip()

    return [
        {
            "source_key": "requirements",
            "title": "Customer onboarding requirements",
            "path_or_url_or_text": requirements,
            "source_type": "PRIMARY_REQUIREMENT",
            "priority": "REQUIRED",
            "content_kind": "INLINE_TEXT",
        },
        {
            "source_key": "contract",
            "title": "Customer onboarding contract",
            "path_or_url_or_text": contract,
            "source_type": "PRIMARY_CONTRACT",
            "priority": "HIGH",
            "content_kind": "INLINE_TEXT",
        },
        {
            "source_key": "glossary",
            "title": "Customer onboarding glossary",
            "path_or_url_or_text": glossary,
            "source_type": "SUPPORTING_GLOSSARY",
            "priority": "NORMAL",
            "content_kind": "INLINE_TEXT",
        },
    ]


def _parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    default_output = repo_root / "tmp" / "ba-runner-demo"

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--feature-key",
        default="customer-onboarding",
        help="Feature key used by the BA run store.",
    )
    parser.add_argument(
        "--notebook-id",
        help="Reuse an existing NotebookLM notebook instead of creating a fresh demo notebook.",
    )
    parser.add_argument(
        "--notebook-title",
        help="Optional title for a newly created demo notebook.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output,
        help="Workspace root passed to ba.run_pipeline (default: %(default)s).",
    )
    return parser.parse_args()


def _structured_payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured

    content = getattr(result, "content", None) or []
    if content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            return json.loads(text)

    raise RuntimeError("Tool call returned neither structuredContent nor JSON text fallback.")


async def _call_tool(
    session: ClientSession,
    *,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await session.call_tool(name, arguments or {})
    if getattr(result, "isError", False):
        payload = _structured_payload(result)
        raise RuntimeError(f"{name} failed: {json.dumps(payload, indent=2)}")
    return _structured_payload(result)


async def _resolve_notebook_id(
    session: ClientSession,
    *,
    notebook_id: str | None,
    notebook_title: str | None,
) -> str:
    if notebook_id:
        return notebook_id

    title = notebook_title or f"BA MCP Demo {datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    created = await _call_tool(
        session,
        name="notebooklm_notebooks_create",
        arguments={"title": title},
    )
    return created["notebook_id"]


async def _main() -> None:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "notebooklm_mcp", "serve"],
        cwd=repo_root,
    )

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            notebook_id = await _resolve_notebook_id(
                session,
                notebook_id=args.notebook_id,
                notebook_title=args.notebook_title,
            )

            pipeline = await _call_tool(
                session,
                name="ba.run_pipeline",
                arguments={
                    "notebook_id": notebook_id,
                    "feature_key": args.feature_key,
                    "mode": "balanced",
                    "output_dir": str(output_dir),
                    "sources": _demo_sources(),
                },
            )

            status = await _call_tool(
                session,
                name="ba.status",
                arguments={
                    "feature_key": args.feature_key,
                    "run_id": pipeline["run_id"],
                    "output_dir": str(output_dir),
                },
            )

    summary = {
        "notebook_id": notebook_id,
        "feature_key": pipeline["feature_key"],
        "run_id": pipeline["run_id"],
        "resolved_output_dir": pipeline["resolved_output_dir"],
        "run_status": status["result"]["state"]["status"],
        "current_step": status["result"]["progress"]["current_step"],
        "next_tool": status["result"]["progress"]["next_tool"],
        "validation": pipeline["result"].get("validation"),
        "bundle_files": pipeline["result"].get("bundle_files", {}),
        "warnings": pipeline.get("warnings", []),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
