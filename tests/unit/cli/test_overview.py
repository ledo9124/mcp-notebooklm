"""Tests for the canonical overview workflow command."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from notebooklm.local.db import connect_db
from notebooklm.local.events import list_run_events
from notebooklm.local.repositories import QueryResultRepository, QueryRunRepository
from notebooklm.notebooklm_cli import cli

from .conftest import create_mock_client, patch_client_for_module


def test_overview_shows_summary(runner, mock_auth, mock_fetch_tokens):
    with patch_client_for_module("overview") as mock_client_cls:
        mock_client = create_mock_client()
        mock_description = MagicMock()
        mock_description.summary = "This notebook is a concise market overview."
        mock_description.suggested_topics = []
        mock_client.notebooks.get_description = AsyncMock(return_value=mock_description)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(cli, ["overview", "-n", "nb_123"])

    assert result.exit_code == 0
    assert "Overview" in result.output
    assert "concise market overview" in result.output


def test_overview_json_envelope_includes_topics(runner, mock_auth, mock_fetch_tokens):
    with patch_client_for_module("overview") as mock_client_cls:
        mock_client = create_mock_client()
        first_topic = MagicMock()
        first_topic.question = "What changed this quarter?"
        first_topic.prompt = "Explain the quarter."
        second_topic = MagicMock()
        second_topic.question = "Which risks are material?"
        second_topic.prompt = "List the risks."
        mock_description = MagicMock()
        mock_description.summary = "Quarterly overview summary."
        mock_description.suggested_topics = [first_topic, second_topic]
        mock_client.notebooks.get_description = AsyncMock(return_value=mock_description)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(cli, ["overview", "-n", "nb_123", "--topics", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["route"]["intent"] == "QUERY"
    assert payload["route"]["mode"] == "summary"
    assert payload["route"]["notebook_id"] == "nb_123"
    assert payload["route"]["source_of_truth"] == "remote_http"
    assert payload["route"]["cache_mode"] == "refresh"
    assert payload["route"]["transport"]["kind"] == "httpx"
    assert payload["result"]["summary"] == "Quarterly overview summary."
    assert payload["cache_updates"]["tables_touched"] == [
        "query_runs",
        "query_results",
        "run_events",
    ]
    assert payload["result"]["suggested_topics"] == [
        {
            "question": "What changed this quarter?",
            "prompt": "Explain the quarter.",
        },
        {
            "question": "Which risks are material?",
            "prompt": "List the risks.",
        },
    ]


def test_overview_persists_query_history(runner, mock_auth, mock_fetch_tokens):
    with patch_client_for_module("overview") as mock_client_cls:
        mock_client = create_mock_client()
        mock_description = MagicMock()
        mock_description.summary = "Persisted overview summary."
        mock_description.suggested_topics = []
        mock_client.notebooks.get_description = AsyncMock(return_value=mock_description)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(cli, ["overview", "-n", "nb_123", "--json"])

    assert result.exit_code == 0
    with connect_db() as connection:
        query_runs = QueryRunRepository(connection).list_for_notebook("nb_123")
        assert len(query_runs) == 1
        run = query_runs[0]
        query_result = QueryResultRepository(connection).get(run.id)
        events = list_run_events(connection, run.trace_id)

    assert run.intent == "overview"
    assert run.mode == "summary"
    assert run.status == "completed"
    assert run.prompt_text == "overview"
    assert query_result is not None
    assert query_result.result_type == "summary"
    assert query_result.answer_text == "Persisted overview summary."
    assert [event.kind for event in events] == ["route.resolved", "cache.miss"]
    assert all(event.run_id == run.id for event in events)
    assert events[0].payload["command"] == "overview"
    assert events[1].payload["entity"] == "query_results"
