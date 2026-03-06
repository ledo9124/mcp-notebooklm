"""Workflow macro tools for notebooklm-mcp."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import inspect
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any


from notebooklm.exceptions import ValidationError
from notebooklm.rpc.types import ChatGoal, ChatResponseLength, source_status_to_str
from notebooklm.types import UNSET, ChatSettings, Source

from .._errors import handle_mcp_errors, sanitize_error_message
from .._fingerprint import fingerprint_settings
from .._mapping import map_from_enum, map_to_enum
from .._result import make_tool_result

DEFAULT_TIMEOUT_MS = 120_000
MAX_TIMEOUT_MS = 300_000
DEFAULT_POLL_INTERVAL_MS = 1_500
MIN_POLL_INTERVAL_MS = 250
MAX_POLL_INTERVAL_MS = 10_000
DEFAULT_IMPORT_CONCURRENCY = 3
MAX_IMPORT_CONCURRENCY = 8
DEFAULT_INDEX_NOTE_TITLE = "Notebook Index (auto)"
DEFAULT_RESEARCH_TIMEOUT_MS = 60_000
DEFAULT_RESEARCH_NOTE_TITLE = "Research Note (auto)"
INDEX_PROMPT = (
    "Create a concise notebook index with sections for key themes, "
    "important sources, and recommended follow-up questions."
)

_UNSET_ARG = object()


def _now() -> float:
    return time.monotonic()


def _resolve_app_context(ctx: MCPContext) -> Any:
    request_context = getattr(ctx, "request_context", None)
    app = getattr(request_context, "lifespan_context", None)
    if app is None:
        app = getattr(ctx, "lifespan_context", None)
    if app is not None and hasattr(app, "client"):
        return app
    raise RuntimeError("NotebookLM MCP lifespan context is unavailable.")


@contextlib.asynccontextmanager
async def _acquire_slot(app: Any):
    acquire_slot = getattr(app, "acquire_slot", None)
    if callable(acquire_slot):
        async with acquire_slot():
            yield
        return
    yield


async def _report_progress(ctx: MCPContext, current: int, total: int, message: str) -> None:
    reporter = getattr(ctx, "report_progress", None)
    if not callable(reporter):
        return

    attempts = (
        {"current": current, "total": total, "message": message},
        {"progress": current, "total": total, "message": message},
        {"current": current, "total": total},
    )
    for kwargs in attempts:
        try:
            value = reporter(**kwargs)
        except TypeError:
            continue
        if inspect.isawaitable(value):
            await value
        return

    with contextlib.suppress(Exception):
        value = reporter(current, total, message)
        if inspect.isawaitable(value):
            await value


def _require_text(value: str | None, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")
    return value.strip()


def _coerce_bool(value: Any, *, field: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValidationError(f"{field} must be a boolean.")
    return value


def _coerce_int(
    value: Any,
    *,
    field: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if value is None:
        number = default
    elif isinstance(value, int) and not isinstance(value, bool):
        number = value
    else:
        raise ValidationError(f"{field} must be an integer.")

    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} must be >= {minimum}.")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{field} must be <= {maximum}.")
    return number


def _normalize_url(url: str) -> str:
    return url.strip().casefold()


def _normalize_title(title: str) -> str:
    return title.strip().casefold()


def _serialize_source_statuses(sources: list[Source]) -> list[dict[str, str]]:
    return [
        {
            "source_id": source.id,
            "status": source_status_to_str(source.status),
        }
        for source in sources
    ]


async def _wait_for_all_sources_ready(
    app: Any,
    notebook_id: str,
    *,
    timeout_ms: int,
    poll_interval_ms: int,
) -> tuple[bool, list[dict[str, str]]]:
    if timeout_ms <= 0:
        raise ValidationError("timeout_ms must be > 0.")

    deadline = _now() + (timeout_ms / 1000.0)
    statuses: list[dict[str, str]] = []

    while True:
        async with _acquire_slot(app):
            sources = await app.client.sources.list(notebook_id)

        statuses = _serialize_source_statuses(sources)
        if not statuses:
            return True, statuses
        if all(item["status"] == "ready" for item in statuses):
            return True, statuses
        if any(item["status"] == "error" for item in statuses):
            return False, statuses
        if _now() >= deadline:
            return False, statuses

        await asyncio.sleep(poll_interval_ms / 1000.0)


def _parse_sources_payload(sources: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(sources or {})
    urls = payload.get("urls") or []
    files = payload.get("files") or []
    texts = payload.get("texts") or []

    if not isinstance(urls, list) or not all(isinstance(item, str) for item in urls):
        raise ValidationError("sources.urls must be a string array.")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        raise ValidationError("sources.files must be an array of objects.")
    if not isinstance(texts, list) or not all(isinstance(item, dict) for item in texts):
        raise ValidationError("sources.texts must be an array of objects.")

    return {
        "urls": urls,
        "files": files,
        "texts": texts,
        "dedup": _coerce_bool(payload.get("dedup"), field="sources.dedup", default=True),
        "concurrency": _coerce_int(
            payload.get("concurrency"),
            field="sources.concurrency",
            default=DEFAULT_IMPORT_CONCURRENCY,
            minimum=1,
            maximum=MAX_IMPORT_CONCURRENCY,
        ),
    }


def _build_import_plan(
    source_payload: dict[str, Any],
    *,
    dedup_urls: set[str],
    dedup_titles: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plan: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    seen_urls = set(dedup_urls)
    seen_titles = set(dedup_titles)

    for url in source_payload["urls"]:
        clean_url = _require_text(url, field="sources.urls[]")
        normalized = _normalize_url(clean_url)
        if source_payload["dedup"] and normalized in seen_urls:
            skipped.append({"kind": "url", "url": clean_url, "reason": "duplicate_url"})
            continue
        seen_urls.add(normalized)
        plan.append({"kind": "url", "url": clean_url})

    for text_entry in source_payload["texts"]:
        title = _require_text(text_entry.get("title"), field="sources.texts[].title")
        content = _require_text(text_entry.get("content"), field="sources.texts[].content")
        normalized_title = _normalize_title(title)
        if source_payload["dedup"] and normalized_title in seen_titles:
            skipped.append({"kind": "text", "title": title, "reason": "duplicate_title"})
            continue
        seen_titles.add(normalized_title)
        plan.append({"kind": "text", "title": title, "content": content})

    for file_entry in source_payload["files"]:
        filename = _require_text(file_entry.get("filename"), field="sources.files[].filename")
        mime_type = _require_text(file_entry.get("mime_type"), field="sources.files[].mime_type")
        data_base64 = _require_text(file_entry.get("data_base64"), field="sources.files[].data_base64")
        title = file_entry.get("title")
        if title is not None:
            title = _require_text(title, field="sources.files[].title")
        dedup_title = title or filename
        normalized_title = _normalize_title(dedup_title)
        if source_payload["dedup"] and normalized_title in seen_titles:
            skipped.append(
                {
                    "kind": "file",
                    "filename": filename,
                    "title": title,
                    "reason": "duplicate_title",
                }
            )
            continue
        seen_titles.add(normalized_title)
        plan.append(
            {
                "kind": "file",
                "filename": filename,
                "mime_type": mime_type,
                "data_base64": data_base64,
                "title": title,
            }
        )

    return plan, skipped


async def _import_one_source(
    app: Any,
    notebook_id: str,
    item: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    kind = item["kind"]

    try:
        if kind == "url":
            async with _acquire_slot(app):
                source = await app.client.sources.add_url(
                    notebook_id,
                    item["url"],
                    wait=False,
                )
            return (
                "added",
                {
                    "kind": "url",
                    "url": item["url"],
                    "source_id": source.id,
                    "status": source_status_to_str(source.status),
                },
            )

        if kind == "text":
            async with _acquire_slot(app):
                source = await app.client.sources.add_text(
                    notebook_id,
                    item["title"],
                    item["content"],
                )
            return (
                "added",
                {
                    "kind": "text",
                    "title": item["title"],
                    "source_id": source.id,
                    "status": source_status_to_str(source.status),
                },
            )

        if kind == "file":
            try:
                raw = base64.b64decode(item["data_base64"], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValidationError("sources.files[].data_base64 must be valid base64.") from exc

            temp_path: str | None = None
            suffix = Path(item["filename"]).suffix
            try:
                with tempfile.NamedTemporaryFile(mode="wb", suffix=suffix, delete=False) as temp_file:
                    temp_file.write(raw)
                    temp_path = temp_file.name

                async with _acquire_slot(app):
                    source = await app.client.sources.add_file(
                        notebook_id,
                        temp_path,
                        mime_type=item["mime_type"],
                    )
                    if item.get("title") and source.title != item["title"]:
                        source = await app.client.sources.rename(
                            notebook_id,
                            source.id,
                            item["title"],
                        )
            finally:
                if temp_path:
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(temp_path)

            return (
                "added",
                {
                    "kind": "file",
                    "filename": item["filename"],
                    "title": item.get("title"),
                    "source_id": source.id,
                    "status": source_status_to_str(source.status),
                },
            )

        raise ValidationError(f"Unsupported source kind: {kind!r}")
    except Exception as exc:
        failure_payload: dict[str, Any] = {"kind": kind}
        for field in ("url", "title", "filename"):
            if field in item:
                failure_payload[field] = item[field]
        failure_payload["error"] = sanitize_error_message(str(exc))
        return "failed", failure_payload


def _serialize_settings(settings: ChatSettings) -> dict[str, Any]:
    goal = map_from_enum(settings.goal)
    response_length = map_from_enum(settings.response_length)
    payload: dict[str, Any] = {
        "goal": goal,
        "response_length": response_length,
        "custom_prompt_set": settings.custom_prompt is not None,
        "fingerprint": fingerprint_settings(goal, response_length, settings.custom_prompt),
    }
    if settings.custom_prompt is not None:
        payload["custom_prompt_len"] = len(settings.custom_prompt)
    return payload


def _citation_location(reference: Any) -> str | None:
    start = getattr(reference, "start_char", None)
    end = getattr(reference, "end_char", None)
    if start is None and end is None:
        return None
    if start is not None and end is not None:
        return f"{start}-{end}"
    if start is not None:
        return str(start)
    return str(end)


async def _collect_citations(app: Any, notebook_id: str, ask_result: Any) -> list[dict[str, Any]]:
    references = list(getattr(ask_result, "references", []) or [])
    if not references:
        return []

    source_ids = {getattr(reference, "source_id", "") for reference in references}
    async with _acquire_slot(app):
        sources = await app.client.sources.list(notebook_id)
    by_id = {source.id: source for source in sources if source.id in source_ids}

    citations: list[dict[str, Any]] = []
    for reference in references:
        source_id = getattr(reference, "source_id", "")
        citation: dict[str, Any] = {"source_id": source_id}
        source = by_id.get(source_id)
        if source is not None and source.title:
            citation["title"] = source.title
        if source is not None and source.url:
            citation["url"] = source.url
        quote = getattr(reference, "cited_text", None)
        if quote:
            citation["quote"] = quote
        location = _citation_location(reference)
        if location is not None:
            citation["location"] = location
        citations.append(citation)

    return citations


def _to_text(answer: str) -> str:
    text = re.sub(r"^#{1,6}\s*", "", answer, flags=re.MULTILINE)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"\[(?P<label>[^\]]+)\]\([^)]+\)", r"\g<label>", text)
    return text.strip()


def _compose_research_note(
    note_title: str,
    *,
    question: str,
    answer: str,
    citations: list[dict[str, Any]],
    include_question: bool,
) -> str:
    lines = [f"# Research Note: {note_title}"]
    if include_question:
        lines.extend(["", "## Question", question.strip()])
    lines.extend(["", "## Answer", answer.strip()])

    lines.extend(["", "## Sources Cited"])
    if citations:
        for citation in citations:
            label = citation.get("title") or citation.get("source_id") or "unknown-source"
            quote = str(citation.get("quote", "")).strip()
            if quote:
                quote = quote[:240]
                quote_text = f": \"{quote}\""
            else:
                quote_text = ""
            location = citation.get("location")
            location_text = f" ({location})" if location else ""
            lines.append(f"- {label}{quote_text}{location_text}")
    else:
        lines.append("- No citations available.")

    return "\n".join(lines).strip()


async def _apply_chat_settings(
    app: Any,
    notebook_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    mode = str(payload.get("mode", "patch")).strip().lower()
    if mode not in {"patch", "set"}:
        raise ValidationError("apply_settings.mode must be one of: patch, set.")

    goal_value = payload.get("goal")
    response_length_value = payload.get("response_length")
    strict = _coerce_bool(payload.get("strict"), field="apply_settings.strict", default=True)

    if mode == "patch":
        mapped_goal = UNSET if goal_value is None else map_to_enum(goal_value, ChatGoal, field_name="goal")
        mapped_length = (
            UNSET
            if response_length_value is None
            else map_to_enum(response_length_value, ChatResponseLength, field_name="response_length")
        )
        if "custom_prompt" in payload:
            custom_prompt = payload["custom_prompt"]
            if custom_prompt is not None and not isinstance(custom_prompt, str):
                raise ValidationError("apply_settings.custom_prompt must be a string or null.")
        else:
            custom_prompt = UNSET
        async with _acquire_slot(app):
            after = await app.client.chat.update_settings(
                notebook_id,
                goal=mapped_goal,
                response_length=mapped_length,
                custom_prompt=custom_prompt,
                strict=strict,
            )
        return _serialize_settings(after)

    goal = (
        ChatGoal.DEFAULT
        if goal_value is None
        else map_to_enum(goal_value, ChatGoal, field_name="goal")
    )
    response_length = (
        ChatResponseLength.DEFAULT
        if response_length_value is None
        else map_to_enum(response_length_value, ChatResponseLength, field_name="response_length")
    )

    custom_prompt_value: str | None | object = payload.get("custom_prompt", _UNSET_ARG)
    if custom_prompt_value is _UNSET_ARG:
        custom_prompt = None
    elif custom_prompt_value is None:
        custom_prompt = None
    elif isinstance(custom_prompt_value, str):
        custom_prompt = custom_prompt_value
    else:
        raise ValidationError("apply_settings.custom_prompt must be a string or null.")

    target = ChatSettings(
        goal=goal,
        response_length=response_length,
        custom_prompt=custom_prompt,
        source="server",
    )
    async with _acquire_slot(app):
        await app.client.chat.set_settings(notebook_id, target)
        after = await app.client.chat.get_settings(notebook_id, strict=False)
    return _serialize_settings(after)


@handle_mcp_errors
async def notebooklm_workflow_bootstrap_notebook(
    ctx: MCPContext,
    notebook_id: str | None = None,
    title: str | None = None,
    sources: dict[str, Any] | None = None,
    wait_ready: bool = True,
    timeout_ms: int | None = None,
    poll_interval_ms: int | None = None,
    generate_index_note: bool = True,
    index_note_title: str | None = None,
    apply_settings: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create/reuse notebook, import sources, optionally wait/index/settings in one call."""
    if notebook_id is None and title is None:
        raise ValidationError("title is required when notebook_id is not provided.")
    if notebook_id is not None:
        notebook_id = _require_text(notebook_id, field="notebook_id")
    if title is not None:
        title = _require_text(title, field="title")

    source_payload = _parse_sources_payload(sources)
    wait_ready = _coerce_bool(wait_ready, field="wait_ready", default=True)
    generate_index_note = _coerce_bool(
        generate_index_note,
        field="generate_index_note",
        default=True,
    )
    dry_run = _coerce_bool(dry_run, field="dry_run", default=False)
    timeout_ms = _coerce_int(
        timeout_ms,
        field="timeout_ms",
        default=DEFAULT_TIMEOUT_MS,
        minimum=1,
        maximum=MAX_TIMEOUT_MS,
    )
    poll_interval_ms = _coerce_int(
        poll_interval_ms,
        field="poll_interval_ms",
        default=DEFAULT_POLL_INTERVAL_MS,
        minimum=MIN_POLL_INTERVAL_MS,
        maximum=MAX_POLL_INTERVAL_MS,
    )
    note_title = (index_note_title or DEFAULT_INDEX_NOTE_TITLE).strip() or DEFAULT_INDEX_NOTE_TITLE

    planned_stages: list[str] = ["prepare_notebook", "import_sources"]
    if wait_ready:
        planned_stages.append("wait_ready")
    if generate_index_note:
        planned_stages.append("index_note")
    if apply_settings is not None:
        planned_stages.append("apply_settings")

    if dry_run:
        return make_tool_result(
            {
                "notebook": {
                    "notebook_id": notebook_id or "__new__",
                    "title": title or "(new notebook)",
                    "created": notebook_id is None,
                },
                "import": {"added": [], "skipped": [], "failed": []},
                "ready": False,
                "index_note": {"created": False} if generate_index_note else None,
                "settings": {"applied": False} if apply_settings is not None else None,
                "warnings": ["dry_run=true: no NotebookLM mutations were executed."],
                "plan": planned_stages,
            }
        )

    app = _resolve_app_context(ctx)
    warnings: list[str] = []

    total_stages = len(planned_stages)
    stage_index = 0

    stage_index += 1
    await _report_progress(ctx, stage_index, total_stages, "Preparing notebook")
    if notebook_id is None:
        assert title is not None
        async with _acquire_slot(app):
            notebook = await app.client.notebooks.create(title)
        resolved_notebook_id = notebook.id
        resolved_title = notebook.title
        created = True
    else:
        async with _acquire_slot(app):
            notebook = await app.client.notebooks.get(notebook_id)
        resolved_notebook_id = notebook_id
        resolved_title = notebook.title or (title or notebook_id)
        created = False

    dedup_urls: set[str] = set()
    dedup_titles: set[str] = set()
    if source_payload["dedup"]:
        async with _acquire_slot(app):
            existing_sources = await app.client.sources.list(resolved_notebook_id)
        dedup_urls = {_normalize_url(src.url) for src in existing_sources if src.url}
        dedup_titles = {_normalize_title(src.title) for src in existing_sources if src.title}

    import_plan, skipped = _build_import_plan(
        source_payload,
        dedup_urls=dedup_urls,
        dedup_titles=dedup_titles,
    )

    stage_index += 1
    await _report_progress(
        ctx,
        stage_index,
        total_stages,
        f"Importing {len(import_plan)} source(s)",
    )

    added: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    if import_plan:
        semaphore = asyncio.Semaphore(source_payload["concurrency"])

        async def _worker(item: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            async with semaphore:
                return await _import_one_source(app, resolved_notebook_id, item)

        tasks = [asyncio.create_task(_worker(item)) for item in import_plan]
        results = await asyncio.gather(*tasks)
        for current, (status, payload) in enumerate(results, start=1):
            if status == "added":
                added.append(payload)
            else:
                failed.append(payload)
            await _report_progress(
                ctx,
                current,
                len(results),
                f"Import progress {current}/{len(results)}",
            )

    ready = False
    statuses: list[dict[str, str]] = []
    if wait_ready:
        stage_index += 1
        await _report_progress(ctx, stage_index, total_stages, "Waiting for sources to be ready")
        ready, statuses = await _wait_for_all_sources_ready(
            app,
            resolved_notebook_id,
            timeout_ms=timeout_ms,
            poll_interval_ms=poll_interval_ms,
        )
        if not ready:
            warnings.append("Not all sources reached ready status before timeout.")

    index_note_result: dict[str, Any] | None = None
    if generate_index_note:
        stage_index += 1
        await _report_progress(ctx, stage_index, total_stages, "Generating index note")
        index_note_result = {"created": False}
        try:
            async with _acquire_slot(app):
                answer = await app.client.chat.ask(resolved_notebook_id, INDEX_PROMPT)
            content = answer.answer.strip()
            if content:
                async with _acquire_slot(app):
                    source = await app.client.sources.add_text(
                        resolved_notebook_id,
                        note_title,
                        content,
                    )
                index_note_result = {"created": True, "source_id": source.id}
            else:
                warnings.append("Index note generation returned empty content.")
        except Exception as exc:  # pragma: no cover - covered via warning behavior tests
            warnings.append(f"Index note step failed: {sanitize_error_message(str(exc))}")

    settings_result: dict[str, Any] | None = None
    if apply_settings is not None:
        if not isinstance(apply_settings, dict):
            raise ValidationError("apply_settings must be an object.")
        stage_index += 1
        await _report_progress(ctx, stage_index, total_stages, "Applying chat settings")
        settings_result = {"applied": False}
        try:
            after = await _apply_chat_settings(app, resolved_notebook_id, apply_settings)
            settings_result = {"applied": True, "after": after}
        except ValidationError:
            raise
        except Exception as exc:  # pragma: no cover - covered via warning behavior tests
            warnings.append(f"Settings step failed: {sanitize_error_message(str(exc))}")

    response: dict[str, Any] = {
        "notebook": {
            "notebook_id": resolved_notebook_id,
            "title": resolved_title,
            "created": created,
        },
        "import": {
            "added": added,
            "skipped": skipped,
            "failed": failed,
        },
        "ready": ready,
    }

    if statuses:
        response["statuses"] = statuses
    if index_note_result is not None:
        response["index_note"] = index_note_result
    if settings_result is not None:
        response["settings"] = settings_result
    if warnings:
        response["warnings"] = warnings

    return make_tool_result(response)


@handle_mcp_errors
async def notebooklm_workflow_research(
    ctx: MCPContext,
    notebook_id: str,
    question: str,
    ensure_ready: bool = True,
    timeout_ms: int | None = None,
    poll_interval_ms: int | None = None,
    citations: bool = True,
    format: str = "markdown",
    conversation_id: str | None = None,
    save_as_note: bool = False,
    note_title: str | None = None,
    note_include_question: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """One-call research flow: readiness check, ask, optional note save."""
    notebook_id = _require_text(notebook_id, field="notebook_id")
    question = _require_text(question, field="question")

    ensure_ready = _coerce_bool(ensure_ready, field="ensure_ready", default=True)
    citations = _coerce_bool(citations, field="citations", default=True)
    save_as_note = _coerce_bool(save_as_note, field="save_as_note", default=False)
    note_include_question = _coerce_bool(
        note_include_question,
        field="note_include_question",
        default=True,
    )
    dry_run = _coerce_bool(dry_run, field="dry_run", default=False)
    timeout_ms = _coerce_int(
        timeout_ms,
        field="timeout_ms",
        default=DEFAULT_RESEARCH_TIMEOUT_MS,
        minimum=1,
        maximum=MAX_TIMEOUT_MS,
    )
    poll_interval_ms = _coerce_int(
        poll_interval_ms,
        field="poll_interval_ms",
        default=DEFAULT_POLL_INTERVAL_MS,
        minimum=MIN_POLL_INTERVAL_MS,
        maximum=MAX_POLL_INTERVAL_MS,
    )
    output_format = format.strip().lower()
    if output_format not in {"markdown", "text"}:
        raise ValidationError("format must be one of: markdown, text.")
    note_title_value = (note_title or DEFAULT_RESEARCH_NOTE_TITLE).strip() or DEFAULT_RESEARCH_NOTE_TITLE

    planned_stages = ["ensure_ready" if ensure_ready else "skip_ready", "ask_question"]
    if save_as_note:
        planned_stages.append("save_note")

    if dry_run:
        return make_tool_result(
            {
                "ready": not ensure_ready,
                "note": {"created": False} if save_as_note else None,
                "warnings": ["dry_run=true: no NotebookLM mutations were executed."],
                "plan": planned_stages,
            }
        )

    app = _resolve_app_context(ctx)
    warnings: list[str] = []
    stage_total = len(planned_stages)
    stage_index = 0

    ready = True
    statuses: list[dict[str, str]] = []
    if ensure_ready:
        stage_index += 1
        await _report_progress(ctx, stage_index, stage_total, "Checking source readiness")
        ready, statuses = await _wait_for_all_sources_ready(
            app,
            notebook_id,
            timeout_ms=timeout_ms,
            poll_interval_ms=poll_interval_ms,
        )
        if not ready:
            warnings.append("Sources were not ready before timeout; question was not asked.")
            response: dict[str, Any] = {"ready": False, "statuses": statuses}
            if warnings:
                response["warnings"] = warnings
            if save_as_note:
                response["note"] = {"created": False}
            return make_tool_result(response)

    stage_index += 1
    await _report_progress(ctx, stage_index, stage_total, "Asking research question")
    async with _acquire_slot(app):
        ask_result = await app.client.chat.ask(
            notebook_id,
            question,
            conversation_id=conversation_id,
        )
        settings = await app.client.chat.get_settings(notebook_id, strict=False)

    answer_text = ask_result.answer or ""
    rendered_answer = answer_text if output_format == "markdown" else _to_text(answer_text)
    citation_items = await _collect_citations(app, notebook_id, ask_result) if citations else []

    note_result: dict[str, Any] | None = None
    if save_as_note:
        stage_index += 1
        await _report_progress(ctx, stage_index, stage_total, "Saving research note")
        note_result = {"created": False}
        try:
            note_content = _compose_research_note(
                note_title_value,
                question=question,
                answer=rendered_answer,
                citations=citation_items,
                include_question=note_include_question,
            )
            async with _acquire_slot(app):
                source = await app.client.sources.add_text(
                    notebook_id,
                    note_title_value,
                    note_content,
                )
            note_result = {"created": True, "source_id": source.id}
        except Exception as exc:  # pragma: no cover - exercised by warning-path tests
            warnings.append(f"Save note step failed: {sanitize_error_message(str(exc))}")

    response = {
        "ready": ready,
        "answer": rendered_answer,
        "conversation_id": ask_result.conversation_id,
        "used_settings": {
            "goal": map_from_enum(settings.goal),
            "response_length": map_from_enum(settings.response_length),
        },
    }
    if citations:
        response["citations"] = citation_items
    if statuses:
        response["statuses"] = statuses
    if note_result is not None:
        response["note"] = note_result
    if warnings:
        response["warnings"] = warnings

    return make_tool_result(response)


def register_workflow_tools(server: Any) -> None:
    """Register workflow tools with a FastMCP-like server instance."""
    tool = getattr(server, "tool", None)
    if not callable(tool):
        return

    registrations = (
        (
            "notebooklm_workflow_bootstrap_notebook",
            notebooklm_workflow_bootstrap_notebook,
            (
                "One-call notebook bootstrap workflow: create/reuse notebook, import sources, "
                "wait until ready, optionally create index note and apply settings."
            ),
        ),
        (
            "notebooklm_workflow_research",
            notebooklm_workflow_research,
            (
                "One-call research workflow: optionally wait for source readiness, ask a question, "
                "and optionally save a research note source."
            ),
        ),
    )

    for name, handler, description in registrations:
        decorator = tool(name=name, description=description)
        decorator(handler)


__all__ = [
    "notebooklm_workflow_bootstrap_notebook",
    "notebooklm_workflow_research",
    "register_workflow_tools",
]
