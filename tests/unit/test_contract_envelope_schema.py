"""Unit tests for the canonical contract envelope dataclasses."""

import json

from notebooklm.contracts.envelope_schema import (
    CacheUpdates,
    Diagnostics,
    Envelope,
    Freshness,
    Route,
    Transport,
)
from notebooklm.contracts.intents import Intent


def test_envelope_to_dict_matches_core_contract_shape():
    """The normalized envelope should match the Phase-0 JSON contract shape."""
    envelope = Envelope(
        ok=True,
        trace_id="trc_123",
        run_id="run_123",
        route=Route(
            intent=Intent.QUERY,
            mode="answer",
            notebook_id="nb_123",
            profile_id="default",
            source_of_truth="remote_http",
            cache_mode="smart",
            reason="Structured query command",
            transport=Transport(
                kind="httpx",
                endpoint="/rpc/query",
                rpcid="QueryNotebook",
            ),
        ),
        freshness=Freshness(
            notebook_index_age_s=5,
            notebook_detail_age_s=1,
            used_cached_result=False,
        ),
        result={"answer": "Grounded answer"},
        cache_updates=CacheUpdates(
            tables_touched=["query_runs", "query_results"],
            invalidated=[],
        ),
        diagnostics=Diagnostics(retries=1, auth_refreshed=False, elapsed_ms=287),
    )

    assert envelope.to_dict() == {
        "ok": True,
        "trace_id": "trc_123",
        "run_id": "run_123",
        "route": {
            "intent": "QUERY",
            "mode": "answer",
            "notebook_id": "nb_123",
            "profile_id": "default",
            "source_of_truth": "remote_http",
            "cache_mode": "smart",
            "reason": "Structured query command",
            "transport": {
                "kind": "httpx",
                "endpoint": "/rpc/query",
                "rpcid": "QueryNotebook",
            },
        },
        "freshness": {
            "notebook_index_age_s": 5,
            "notebook_detail_age_s": 1,
            "used_cached_result": False,
        },
        "result": {"answer": "Grounded answer"},
        "cache_updates": {
            "tables_touched": ["query_runs", "query_results"],
            "invalidated": [],
        },
        "diagnostics": {
            "retries": 1,
            "auth_refreshed": False,
            "elapsed_ms": 287,
        },
    }

    json.dumps(envelope.to_dict())


def test_envelope_allows_null_freshness_for_doctor_flows():
    """Doctor-style envelopes may omit freshness and serialize it as null."""
    envelope = Envelope(
        ok=True,
        trace_id="trc_doctor",
        run_id="run_doctor",
        route=Route(
            intent=Intent.DOCTOR,
            mode="check",
            notebook_id=None,
            profile_id="default",
            source_of_truth="local_cache",
            cache_mode="offline",
            reason="Doctor checks local state",
            transport=Transport(kind="local"),
        ),
        result={"status": "healthy"},
    )

    assert envelope.to_dict()["freshness"] is None
