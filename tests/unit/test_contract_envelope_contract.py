"""Top-up contract checks for the canonical JSON envelope rules."""

from notebooklm.contracts.envelope_schema import Envelope, Route, Transport
from notebooklm.contracts.intents import Intent


def test_envelope_keeps_required_top_level_fields_when_freshness_is_null():
    """Freshness may be null, but the canonical envelope shape must stay intact."""
    envelope = Envelope(
        ok=True,
        trace_id="trc_inbox",
        run_id="run_inbox",
        route=Route(
            intent=Intent.INBOX_APPLY,
            mode="approve",
            notebook_id=None,
            profile_id="default",
            source_of_truth="mixed",
            cache_mode="network",
            reason="Inbox approval wraps its payload in the canonical envelope",
            transport=Transport(kind="local"),
        ),
        freshness=None,
        result={
            "item": {
                "id": "item_123",
                "origin": "deep_research",
                "kind": "source",
                "state": "pending",
                "approval_required": True,
            }
        },
    )

    assert envelope.to_dict() == {
        "ok": True,
        "trace_id": "trc_inbox",
        "run_id": "run_inbox",
        "route": {
            "intent": "INBOX_APPLY",
            "mode": "approve",
            "notebook_id": None,
            "profile_id": "default",
            "source_of_truth": "mixed",
            "cache_mode": "network",
            "reason": "Inbox approval wraps its payload in the canonical envelope",
            "transport": {
                "kind": "local",
                "endpoint": None,
                "rpcid": None,
            },
        },
        "freshness": None,
        "result": {
            "item": {
                "id": "item_123",
                "origin": "deep_research",
                "kind": "source",
                "state": "pending",
                "approval_required": True,
            }
        },
        "cache_updates": {
            "tables_touched": [],
            "invalidated": [],
        },
        "diagnostics": {
            "retries": 0,
            "auth_refreshed": False,
            "elapsed_ms": 0,
        },
    }
