"""Unit tests for the manifest-facing RPC route registry."""

from notebooklm.contracts.rpc_map import RPC_MAP, load_rpc_map
from notebooklm.rpc import BATCHEXECUTE_URL, QUERY_URL, RPCMethod


def test_rpc_map_covers_the_current_manifest_command_surface():
    """Every manifest command should resolve to one or more transport bindings."""
    rpc_map = load_rpc_map()

    assert set(rpc_map) == {
        ("DOCTOR", "fast"),
        ("DOCTOR", "doctor_check"),
        ("DOCTOR", "doctor_fix"),
        ("DOCTOR", "doctor_bundle"),
        ("GENERATION", "audio"),
        ("GENERATION", "briefing_doc"),
        ("GENERATION", "study_guide"),
        ("LOCAL_METADATA", "events_tail"),
        ("LOCAL_METADATA", "history_search"),
        ("LOCAL_METADATA", "history_show"),
        ("LOCAL_METADATA", "trace_show"),
        ("QUERY", "cache_status"),
        ("LOCAL_MUTATION", "cache_prune"),
        ("LOCAL_MUTATION", "workspace_create"),
        ("LOCAL_MUTATION", "workspace_add"),
        ("LOCAL_MUTATION", "workspace_remove"),
        ("LOCAL_MUTATION", "workspace_index"),
        ("LOCAL_MUTATION", "watch_add"),
        ("LOCAL_MUTATION", "watch_pause"),
        ("LOCAL_MUTATION", "watch_run_now"),
        ("LOCAL_MUTATION", "radar_ignore"),
        ("REMOTE_METADATA", "source_guide"),
        ("REMOTE_METADATA", "sync_notebooks"),
        ("MUTATION", "notebook_delete"),
        ("MUTATION", "source_delete"),
        ("LOCAL_METADATA", "workspace_list"),
        ("LOCAL_METADATA", "workspace_show"),
        ("LOCAL_METADATA", "watch_list"),
        ("QUERY", "answer"),
        ("QUERY", "summary"),
        ("WORKSPACE_QUERY", "workspace_ask"),
        ("WORKSPACE_COMPARE", "workspace_compare"),
        ("RESEARCH", "deep"),
        ("RESEARCH", "fast"),
        ("RESEARCH", "research_import"),
        ("RESEARCH", "research_status"),
        ("RADAR_STATUS", "radar_status"),
        ("RADAR_STATUS", "radar_list"),
        ("RADAR_BRIEF", "radar_brief"),
        ("INBOX_TRIAGE", "inbox_list"),
        ("INBOX_TRIAGE", "inbox_view"),
        ("INBOX_TRIAGE", "inbox_why"),
        ("INBOX_TRIAGE", "inbox_reject"),
        ("INBOX_TRIAGE", "inbox_defer"),
        ("INBOX_APPLY", "inbox_approve"),
        ("INBOX_APPLY", "inbox_import"),
        ("INBOX_APPLY", "inbox_apply_batch"),
    }


def test_query_and_generation_bindings_match_current_transport_calls():
    """Query and generation routes should point at the live client transport surface."""
    ask = RPC_MAP[("QUERY", "answer")]
    overview = RPC_MAP[("QUERY", "summary")]
    summarize = RPC_MAP[("GENERATION", "briefing_doc")]
    study_guide = RPC_MAP[("GENERATION", "study_guide")]
    audio = RPC_MAP[("GENERATION", "audio")]

    assert ask.command_name == "ask"
    assert ask.client_method == "chat.ask"
    assert ask.transport_kind == "httpx"
    assert ask.endpoint == QUERY_URL
    assert ask.rpc_method is None
    assert ask.rpcid is None

    assert overview.command_name == "overview"
    assert overview.client_method == "notebooks.get_description"
    assert overview.endpoint == BATCHEXECUTE_URL
    assert overview.rpc_method is RPCMethod.SUMMARIZE
    assert overview.rpcid == RPCMethod.SUMMARIZE.value

    assert summarize.client_method == "artifacts.generate_report"
    assert study_guide.client_method == "artifacts.generate_report"
    assert audio.client_method == "artifacts.generate_audio"
    assert summarize.rpc_method is RPCMethod.CREATE_ARTIFACT
    assert study_guide.rpc_method is RPCMethod.CREATE_ARTIFACT
    assert audio.rpc_method is RPCMethod.CREATE_ARTIFACT


def test_research_and_mutation_bindings_preserve_httpx_vs_local_transport():
    """Research and mutation routes should keep the correct endpoint/source-path semantics."""
    start_fast = RPC_MAP[("RESEARCH", "fast")]
    start_deep = RPC_MAP[("RESEARCH", "deep")]
    research_import = RPC_MAP[("RESEARCH", "research_import")]
    wait = RPC_MAP[("RESEARCH", "research_status")]
    doctor = RPC_MAP[("DOCTOR", "fast")]
    source_guide = RPC_MAP[("REMOTE_METADATA", "source_guide")]
    sync_notebooks = RPC_MAP[("REMOTE_METADATA", "sync_notebooks")]
    notebook_delete = RPC_MAP[("MUTATION", "notebook_delete")]
    source_delete = RPC_MAP[("MUTATION", "source_delete")]
    cache_status = RPC_MAP[("QUERY", "cache_status")]
    cache_prune = RPC_MAP[("LOCAL_MUTATION", "cache_prune")]

    assert start_fast.rpc_method is RPCMethod.START_FAST_RESEARCH
    assert start_deep.rpc_method is RPCMethod.START_DEEP_RESEARCH
    assert research_import.rpc_method is RPCMethod.IMPORT_RESEARCH
    assert wait.rpc_method is RPCMethod.POLL_RESEARCH
    assert start_fast.source_path_template == "/notebook/{notebook_id}"
    assert start_deep.source_path_template == "/notebook/{notebook_id}"
    assert research_import.source_path_template == "/notebook/{notebook_id}"
    assert wait.source_path_template == "/notebook/{notebook_id}"

    assert source_guide.command_name == "source.guide"
    assert source_guide.client_method == "sources.get_guide"
    assert source_guide.transport_kind == "httpx"
    assert source_guide.endpoint == BATCHEXECUTE_URL
    assert source_guide.rpc_method is RPCMethod.GET_SOURCE_GUIDE
    assert source_guide.source_path_template == "/notebook/{notebook_id}"

    assert sync_notebooks.command_name == "sync.notebooks"
    assert sync_notebooks.client_method == "sync.notebooks"
    assert sync_notebooks.transport_kind == "httpx"
    assert sync_notebooks.endpoint == BATCHEXECUTE_URL
    assert sync_notebooks.rpc_method is None
    assert sync_notebooks.source_path_template is None

    assert notebook_delete.rpc_method is RPCMethod.DELETE_NOTEBOOK
    assert source_delete.rpc_method is RPCMethod.DELETE_SOURCE
    assert notebook_delete.endpoint == BATCHEXECUTE_URL
    assert source_delete.endpoint == BATCHEXECUTE_URL

    assert cache_status.command_name == "cache.status"
    assert cache_status.transport_kind == "local"
    assert cache_status.endpoint is None
    assert cache_status.rpc_method is None

    assert cache_prune.command_name == "cache.prune"
    assert cache_prune.transport_kind == "local"
    assert cache_prune.endpoint is None
    assert cache_prune.rpc_method is None

    assert doctor.command_name == "doctor"
    assert doctor.client_method == "doctor.fast"
    assert doctor.transport_kind == "local"
    assert doctor.endpoint is None
    assert doctor.rpc_method is None


def test_post_mvp_manifest_bindings_use_named_local_routes():
    """Post-MVP manifest inventory should use explicit local route bindings for future lanes."""
    doctor_check = RPC_MAP[("DOCTOR", "doctor_check")]
    doctor_fix = RPC_MAP[("DOCTOR", "doctor_fix")]
    doctor_bundle = RPC_MAP[("DOCTOR", "doctor_bundle")]
    workspace_ask = RPC_MAP[("WORKSPACE_QUERY", "workspace_ask")]
    workspace_compare = RPC_MAP[("WORKSPACE_COMPARE", "workspace_compare")]
    watch_run_now = RPC_MAP[("LOCAL_MUTATION", "watch_run_now")]
    radar_brief = RPC_MAP[("RADAR_BRIEF", "radar_brief")]
    events_tail = RPC_MAP[("LOCAL_METADATA", "events_tail")]
    history_search = RPC_MAP[("LOCAL_METADATA", "history_search")]
    history_show = RPC_MAP[("LOCAL_METADATA", "history_show")]
    trace_show = RPC_MAP[("LOCAL_METADATA", "trace_show")]
    inbox_approve = RPC_MAP[("INBOX_APPLY", "inbox_approve")]
    inbox_reject = RPC_MAP[("INBOX_TRIAGE", "inbox_reject")]

    assert doctor_check.command_name == "doctor.check"
    assert doctor_check.client_method == "doctor.check"
    assert doctor_check.transport_kind == "local"
    assert doctor_check.endpoint is None

    assert doctor_fix.command_name == "doctor.fix"
    assert doctor_fix.client_method == "doctor.fix"
    assert doctor_fix.transport_kind == "local"
    assert doctor_fix.endpoint is None

    assert doctor_bundle.command_name == "doctor.bundle"
    assert doctor_bundle.client_method == "doctor.bundle"
    assert doctor_bundle.transport_kind == "local"
    assert doctor_bundle.endpoint is None

    assert workspace_ask.command_name == "workspace.ask"
    assert workspace_ask.client_method == "workspace.ask"
    assert workspace_ask.transport_kind == "local"
    assert workspace_ask.endpoint is None

    assert workspace_compare.command_name == "workspace.compare"
    assert workspace_compare.client_method == "workspace.compare"
    assert workspace_compare.transport_kind == "local"
    assert workspace_compare.endpoint is None

    assert watch_run_now.command_name == "watch.run-now"
    assert watch_run_now.client_method == "watch.run_now"
    assert watch_run_now.transport_kind == "local"
    assert watch_run_now.endpoint is None

    assert radar_brief.command_name == "radar.brief"
    assert radar_brief.client_method == "radar.brief"
    assert radar_brief.transport_kind == "local"
    assert radar_brief.endpoint is None

    assert events_tail.command_name == "events.tail"
    assert events_tail.client_method == "events.tail"
    assert events_tail.transport_kind == "local"
    assert events_tail.endpoint is None

    assert history_search.command_name == "history.search"
    assert history_search.client_method == "history.search"
    assert history_search.transport_kind == "local"
    assert history_search.endpoint is None

    assert history_show.command_name == "history.show"
    assert history_show.client_method == "history.show"
    assert history_show.transport_kind == "local"
    assert history_show.endpoint is None

    assert trace_show.command_name == "trace.show"
    assert trace_show.client_method == "trace.show"
    assert trace_show.transport_kind == "local"
    assert trace_show.endpoint is None

    assert inbox_approve.command_name == "inbox.approve"
    assert inbox_approve.client_method == "inbox.approve"
    assert inbox_approve.transport_kind == "local"
    assert inbox_approve.endpoint is None

    assert inbox_reject.command_name == "inbox.reject"
    assert inbox_reject.client_method == "inbox.reject"
    assert inbox_reject.transport_kind == "local"
    assert inbox_reject.endpoint is None
