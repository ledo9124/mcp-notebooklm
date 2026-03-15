"""Contract checks for the canonical JSON envelope shape."""

from notebooklm.contracts.envelope_schema import (
    CacheUpdates,
    Diagnostics,
    Envelope,
    Freshness,
    Route,
    Transport,
)
from notebooklm.contracts.intents import Intent


def test_envelope_shape_matches_contract_normalization_section_3():
    """The canonical success envelope should keep the documented field layout."""
    envelope = Envelope(
        ok=True,
        trace_id="trc_contract",
        run_id="run_contract",
        route=Route(
            intent=Intent.RESEARCH,
            mode="start",
            notebook_id="nb_contract",
            profile_id="default",
            source_of_truth="remote_http",
            cache_mode="network",
            reason="research command",
            transport=Transport(
                kind="httpx",
                endpoint="/rpc/research",
                rpcid="StartResearch",
            ),
        ),
        freshness=Freshness(
            notebook_index_age_s=None,
            notebook_detail_age_s=0,
            used_cached_result=False,
        ),
        result={"status": "pending"},
        cache_updates=CacheUpdates(
            tables_touched=["research_runs"],
            invalidated=["query_results"],
        ),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=42),
    ).to_dict()

    assert set(envelope) == {
        "ok",
        "trace_id",
        "run_id",
        "route",
        "freshness",
        "result",
        "cache_updates",
        "diagnostics",
    }
    assert set(envelope["route"]) == {
        "intent",
        "mode",
        "notebook_id",
        "profile_id",
        "source_of_truth",
        "cache_mode",
        "reason",
        "transport",
    }
    assert set(envelope["route"]["transport"]) == {"kind", "endpoint", "rpcid"}
    assert set(envelope["freshness"]) == {
        "notebook_index_age_s",
        "notebook_detail_age_s",
        "used_cached_result",
    }
    assert set(envelope["cache_updates"]) == {"tables_touched", "invalidated"}
    assert set(envelope["diagnostics"]) == {
        "retries",
        "auth_refreshed",
        "elapsed_ms",
    }


def test_doctor_style_envelope_allows_null_freshness():
    """The contract allows `freshness` to be null for doctor-like local checks."""
    envelope = Envelope(
        ok=True,
        trace_id="trc_doctor_contract",
        run_id="run_doctor_contract",
        route=Route(
            intent=Intent.DOCTOR,
            mode="check",
            notebook_id=None,
            profile_id="default",
            source_of_truth="local_cache",
            cache_mode="offline",
            reason="doctor command",
            transport=Transport(kind="local"),
        ),
        result={"status": "healthy"},
    ).to_dict()

    assert envelope["freshness"] is None
