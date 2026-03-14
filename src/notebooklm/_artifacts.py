"""Artifacts API for the reduced NotebookLM MVP surface.

The active supported paths on this branch are audio generation, constrained
report generation, and generation status polling/waiting. Broader helpers are
retained only where adjacent pruning work still depends on them.
"""

import asyncio
import builtins
import logging
from typing import Any

from ._core import ClientCore
from .exceptions import ValidationError
from .rpc import (
    ArtifactStatus,
    ArtifactTypeCode,
    AudioFormat,
    AudioLength,
    ReportFormat,
    RPCError,
    RPCMethod,
    artifact_status_to_str,
)
from .types import Artifact, ArtifactType, GenerationStatus, ReportSuggestion

logger = logging.getLogger(__name__)


_MVP_UNSUPPORTED_MESSAGE = (
    "The active notebooklm-py MVP only supports audio generation, report "
    "generation (briefing-doc and study-guide), and artifact task status polling."
)

_SUPPORTED_REPORT_CONFIGS: dict[ReportFormat, dict[str, str]] = {
    ReportFormat.BRIEFING_DOC: {
        "title": "Briefing Doc",
        "description": "Key insights and important quotes",
        "prompt": (
            "Create a comprehensive briefing document that includes an "
            "Executive Summary, detailed analysis of key themes, important "
            "quotes with context, and actionable insights."
        ),
    },
    ReportFormat.STUDY_GUIDE: {
        "title": "Study Guide",
        "description": "Short-answer quiz, essay questions, glossary",
        "prompt": (
            "Create a comprehensive study guide that includes key concepts, "
            "short-answer practice questions, essay prompts for deeper "
            "exploration, and a glossary of important terms."
        ),
    },
}


def _raise_unsupported_mvp(feature: str) -> None:
    """Raise a consistent error for surfaces pruned from the active MVP."""
    raise ValidationError(f"{feature} is not supported on this branch. {_MVP_UNSUPPORTED_MESSAGE}")


class ArtifactsAPI:
    """Operations on NotebookLM artifacts.

    The active MVP keeps only audio generation, constrained report generation,
    and generation status polling/waiting as supported flows.
    """

    def __init__(self, core: ClientCore, notes_api: object | None = None):
        """Initialize the artifacts API.

        The historical ``notes_api`` argument is retained only for compatibility
        with deferred callers and older tests. The reduced MVP artifact surface
        no longer depends on notes to initialize.
        """
        del notes_api
        self._core = core

    # =========================================================================
    # List/Get Operations
    # =========================================================================

    async def list(
        self, notebook_id: str, artifact_type: ArtifactType | None = None
    ) -> list[Artifact]:
        """List studio artifacts in a notebook.

        This compatibility helper now surfaces only studio-backed artifacts from
        the main artifact listing. Mind maps are no longer merged in from notes.
        """
        logger.debug("Listing artifacts in notebook %s", notebook_id)
        artifacts: list[Artifact] = []

        for art_data in await self._list_raw(notebook_id):
            if isinstance(art_data, list) and art_data:
                artifact = Artifact.from_api_response(art_data)
                if artifact_type is None or artifact.kind == artifact_type:
                    artifacts.append(artifact)

        return artifacts

    async def get(self, notebook_id: str, artifact_id: str) -> Artifact | None:
        """Get a specific artifact by ID."""
        logger.debug("Getting artifact %s from notebook %s", artifact_id, notebook_id)
        artifacts = await self.list(notebook_id)
        for artifact in artifacts:
            if artifact.id == artifact_id:
                return artifact
        return None

    async def list_audio(self, notebook_id: str) -> builtins.list[Artifact]:
        """List audio overview artifacts."""
        return await self.list(notebook_id, ArtifactType.AUDIO)

    async def list_video(self, notebook_id: str) -> builtins.list[Artifact]:
        """List video overview artifacts."""
        _raise_unsupported_mvp("list_video()")

    async def list_reports(self, notebook_id: str) -> builtins.list[Artifact]:
        """List report artifacts."""
        return await self.list(notebook_id, ArtifactType.REPORT)

    async def list_quizzes(self, notebook_id: str) -> builtins.list[Artifact]:
        """List quiz artifacts."""
        _raise_unsupported_mvp("list_quizzes()")

    async def list_flashcards(self, notebook_id: str) -> builtins.list[Artifact]:
        """List flashcard artifacts."""
        _raise_unsupported_mvp("list_flashcards()")

    async def list_infographics(self, notebook_id: str) -> builtins.list[Artifact]:
        """List infographic artifacts."""
        _raise_unsupported_mvp("list_infographics()")

    async def list_slide_decks(self, notebook_id: str) -> builtins.list[Artifact]:
        """List slide deck artifacts."""
        _raise_unsupported_mvp("list_slide_decks()")

    async def list_data_tables(self, notebook_id: str) -> builtins.list[Artifact]:
        """List data table artifacts."""
        _raise_unsupported_mvp("list_data_tables()")

    # =========================================================================
    # Generate Operations
    # =========================================================================

    async def generate_audio(
        self,
        notebook_id: str,
        source_ids: builtins.list[str] | None = None,
        language: str = "en",
        instructions: str | None = None,
        audio_format: AudioFormat | None = None,
        audio_length: AudioLength | None = None,
    ) -> GenerationStatus:
        """Generate an audio overview."""
        if source_ids is None:
            source_ids = await self._core.get_source_ids(notebook_id)

        source_ids_triple = [[[sid]] for sid in source_ids] if source_ids else []
        source_ids_double = [[sid] for sid in source_ids] if source_ids else []

        format_code = audio_format.value if audio_format else None
        length_code = audio_length.value if audio_length else None

        params = [
            [2],
            notebook_id,
            [
                None,
                None,
                1,  # ArtifactTypeCode.AUDIO
                source_ids_triple,
                None,
                None,
                [
                    None,
                    [
                        instructions,
                        length_code,
                        None,
                        source_ids_double,
                        language,
                        None,
                        format_code,
                    ],
                ],
            ],
        ]
        return await self._call_generate(notebook_id, params)

    async def generate_video(
        self,
        notebook_id: str,
        source_ids: builtins.list[str] | None = None,
        language: str = "en",
        instructions: str | None = None,
        video_format: Any | None = None,
        video_style: Any | None = None,
    ) -> GenerationStatus:
        """Video generation is outside the active MVP."""
        _raise_unsupported_mvp("generate_video()")

    async def generate_report(
        self,
        notebook_id: str,
        report_format: ReportFormat = ReportFormat.BRIEFING_DOC,
        source_ids: builtins.list[str] | None = None,
        language: str = "en",
        custom_prompt: str | None = None,
        extra_instructions: str | None = None,
    ) -> GenerationStatus:
        """Generate a report artifact for the supported MVP report formats."""
        if report_format not in _SUPPORTED_REPORT_CONFIGS:
            feature = f"generate_report(report_format={report_format.value!r})"
            _raise_unsupported_mvp(feature)

        if custom_prompt is not None:
            raise ValidationError(
                "custom_prompt is not supported on this branch. "
                "Use extra_instructions with briefing-doc or study-guide."
            )

        if source_ids is None:
            source_ids = await self._core.get_source_ids(notebook_id)

        config = _SUPPORTED_REPORT_CONFIGS[report_format]
        prompt = config["prompt"]
        if extra_instructions:
            prompt = f"{prompt}\n\n{extra_instructions}"

        source_ids_triple = [[[sid]] for sid in source_ids] if source_ids else []
        source_ids_double = [[sid] for sid in source_ids] if source_ids else []

        params = [
            [2],
            notebook_id,
            [
                None,
                None,
                2,  # ArtifactTypeCode.REPORT
                source_ids_triple,
                None,
                None,
                None,
                [
                    None,
                    [
                        config["title"],
                        config["description"],
                        None,
                        source_ids_double,
                        language,
                        prompt,
                        None,
                        True,
                    ],
                ],
            ],
        ]
        return await self._call_generate(notebook_id, params)

    async def generate_study_guide(
        self,
        notebook_id: str,
        source_ids: builtins.list[str] | None = None,
        language: str = "en",
        extra_instructions: str | None = None,
    ) -> GenerationStatus:
        """Generate a study guide report."""
        return await self.generate_report(
            notebook_id,
            report_format=ReportFormat.STUDY_GUIDE,
            source_ids=source_ids,
            language=language,
            extra_instructions=extra_instructions,
        )

    async def generate_quiz(
        self,
        notebook_id: str,
        source_ids: builtins.list[str] | None = None,
        instructions: str | None = None,
        quantity: Any | None = None,
        difficulty: Any | None = None,
    ) -> GenerationStatus:
        """Quiz generation is outside the active MVP."""
        _raise_unsupported_mvp("generate_quiz()")

    async def generate_flashcards(
        self,
        notebook_id: str,
        source_ids: builtins.list[str] | None = None,
        instructions: str | None = None,
        quantity: Any | None = None,
        difficulty: Any | None = None,
    ) -> GenerationStatus:
        """Flashcard generation is outside the active MVP."""
        _raise_unsupported_mvp("generate_flashcards()")

    async def generate_infographic(
        self,
        notebook_id: str,
        source_ids: builtins.list[str] | None = None,
        language: str = "en",
        instructions: str | None = None,
        orientation: Any | None = None,
        detail_level: Any | None = None,
    ) -> GenerationStatus:
        """Infographic generation is outside the active MVP."""
        _raise_unsupported_mvp("generate_infographic()")

    async def generate_slide_deck(
        self,
        notebook_id: str,
        source_ids: builtins.list[str] | None = None,
        language: str = "en",
        instructions: str | None = None,
        slide_format: Any | None = None,
        slide_length: Any | None = None,
    ) -> GenerationStatus:
        """Slide deck generation is outside the active MVP."""
        _raise_unsupported_mvp("generate_slide_deck()")

    async def revise_slide(
        self,
        notebook_id: str,
        artifact_id: str,
        slide_index: int,
        prompt: str,
    ) -> GenerationStatus:
        """Slide revision is outside the active MVP."""
        _raise_unsupported_mvp("revise_slide()")

    async def generate_data_table(
        self,
        notebook_id: str,
        source_ids: builtins.list[str] | None = None,
        language: str = "en",
        instructions: str | None = None,
    ) -> GenerationStatus:
        """Data-table generation is outside the active MVP."""
        _raise_unsupported_mvp("generate_data_table()")

    async def generate_mind_map(
        self,
        notebook_id: str,
        source_ids: builtins.list[str] | None = None,
    ) -> dict[str, Any]:
        """Mind-map generation is outside the active MVP."""
        _raise_unsupported_mvp("generate_mind_map()")

    # =========================================================================
    # Download Operations
    # =========================================================================

    async def download_audio(
        self, notebook_id: str, output_path: str, artifact_id: str | None = None
    ) -> str:
        """Audio downloads are outside the active MVP."""
        _raise_unsupported_mvp("download_audio()")

    async def download_video(
        self, notebook_id: str, output_path: str, artifact_id: str | None = None
    ) -> str:
        """Video downloads are outside the active MVP."""
        _raise_unsupported_mvp("download_video()")

    async def download_infographic(
        self, notebook_id: str, output_path: str, artifact_id: str | None = None
    ) -> str:
        """Infographic downloads are outside the active MVP."""
        _raise_unsupported_mvp("download_infographic()")

    async def download_slide_deck(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
        output_format: str = "pdf",
    ) -> str:
        """Slide-deck downloads are outside the active MVP."""
        _raise_unsupported_mvp("download_slide_deck()")

    async def download_report(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
    ) -> str:
        """Report downloads are outside the active MVP."""
        _raise_unsupported_mvp("download_report()")

    async def download_mind_map(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
    ) -> str:
        """Mind-map downloads are outside the active MVP."""
        _raise_unsupported_mvp("download_mind_map()")

    async def download_data_table(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
    ) -> str:
        """Data-table downloads are outside the active MVP."""
        _raise_unsupported_mvp("download_data_table()")

    async def download_quiz(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
        output_format: str = "json",
    ) -> str:
        """Quiz downloads are outside the active MVP."""
        _raise_unsupported_mvp("download_quiz()")

    async def download_flashcards(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
        output_format: str = "json",
    ) -> str:
        """Flashcard downloads are outside the active MVP."""
        _raise_unsupported_mvp("download_flashcards()")

    # =========================================================================
    # Management / Status Operations
    # =========================================================================

    async def delete(self, notebook_id: str, artifact_id: str) -> bool:
        """Delete an artifact."""
        logger.debug("Deleting artifact %s from notebook %s", artifact_id, notebook_id)
        params = [[2], artifact_id]
        await self._core.rpc_call(
            RPCMethod.DELETE_ARTIFACT,
            params,
            source_path=f"/notebook/{notebook_id}",
            allow_null=True,
        )
        return True

    async def rename(self, notebook_id: str, artifact_id: str, new_title: str) -> None:
        """Rename an artifact."""
        params = [[artifact_id, new_title], [["title"]]]
        await self._core.rpc_call(
            RPCMethod.RENAME_ARTIFACT,
            params,
            source_path=f"/notebook/{notebook_id}",
            allow_null=True,
        )

    async def poll_status(self, notebook_id: str, task_id: str) -> GenerationStatus:
        """Poll the status of a generation task."""
        artifacts_data = await self._list_raw(notebook_id)
        for art in artifacts_data:
            if len(art) > 0 and art[0] == task_id:
                status_code = art[4] if len(art) > 4 else 0
                artifact_type = art[2] if len(art) > 2 else 0

                if status_code == ArtifactStatus.COMPLETED and not self._is_media_ready(
                    art, artifact_type
                ):
                    type_name = self._get_artifact_type_name(artifact_type)
                    logger.debug(
                        "Artifact %s (type=%s) status=COMPLETED but media not ready, continuing poll",
                        task_id,
                        type_name,
                    )
                    status_code = ArtifactStatus.PROCESSING

                status = artifact_status_to_str(status_code)
                return GenerationStatus(task_id=task_id, status=status)

        return GenerationStatus(task_id=task_id, status="pending")

    async def wait_for_completion(
        self,
        notebook_id: str,
        task_id: str,
        initial_interval: float = 2.0,
        max_interval: float = 10.0,
        timeout: float = 300.0,
        poll_interval: float | None = None,
    ) -> GenerationStatus:
        """Wait for a generation task to complete."""
        if poll_interval is not None:
            import warnings

            warnings.warn(
                "poll_interval is deprecated, use initial_interval instead",
                DeprecationWarning,
                stacklevel=2,
            )
            initial_interval = poll_interval

        start_time = asyncio.get_running_loop().time()
        current_interval = initial_interval

        while True:
            status = await self.poll_status(notebook_id, task_id)

            if status.is_complete or status.is_failed:
                return status

            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed > timeout:
                raise TimeoutError(f"Task {task_id} timed out after {timeout}s")

            remaining_time = timeout - elapsed
            sleep_duration = min(current_interval, remaining_time)
            if sleep_duration > 0:
                await asyncio.sleep(sleep_duration)

            current_interval = min(current_interval * 2, max_interval)

    # =========================================================================
    # Export / Suggestions
    # =========================================================================

    async def export_report(
        self,
        notebook_id: str,
        artifact_id: str,
        title: str = "Export",
        export_type: Any | None = None,
    ) -> Any:
        """Report export is outside the active MVP."""
        _raise_unsupported_mvp("export_report()")

    async def export_data_table(
        self,
        notebook_id: str,
        artifact_id: str,
        title: str = "Export",
    ) -> Any:
        """Data-table export is outside the active MVP."""
        _raise_unsupported_mvp("export_data_table()")

    async def export(
        self,
        notebook_id: str,
        artifact_id: str | None = None,
        content: str | None = None,
        title: str = "Export",
        export_type: Any | None = None,
    ) -> Any:
        """Generic export is outside the active MVP."""
        _raise_unsupported_mvp("export()")

    async def suggest_reports(
        self,
        notebook_id: str,
    ) -> builtins.list[ReportSuggestion]:
        """Get AI-suggested report formats for a notebook."""
        params = [[2], notebook_id]

        result = await self._core.rpc_call(
            RPCMethod.GET_SUGGESTED_REPORTS,
            params,
            source_path=f"/notebook/{notebook_id}",
            allow_null=True,
        )

        suggestions = []
        if result and isinstance(result, list) and len(result) > 0:
            items = result[0] if isinstance(result[0], list) else result
            for item in items:
                if isinstance(item, list) and len(item) >= 5:
                    suggestions.append(
                        ReportSuggestion(
                            title=item[0] if isinstance(item[0], str) else "",
                            description=item[1] if isinstance(item[1], str) else "",
                            prompt=item[4] if isinstance(item[4], str) else "",
                            audience_level=item[5] if len(item) > 5 else 2,
                        )
                    )

        return suggestions

    # =========================================================================
    # Private Helpers
    # =========================================================================

    async def _call_generate(
        self, notebook_id: str, params: builtins.list[Any]
    ) -> GenerationStatus:
        """Make a generation RPC call with error handling."""
        artifact_type = params[2][2] if len(params) > 2 and len(params[2]) > 2 else "unknown"
        logger.debug("Generating artifact type=%s in notebook %s", artifact_type, notebook_id)
        try:
            result = await self._core.rpc_call(
                RPCMethod.CREATE_ARTIFACT,
                params,
                source_path=f"/notebook/{notebook_id}",
                allow_null=True,
            )
            return self._parse_generation_result(result)
        except RPCError as e:
            if e.rpc_code == "USER_DISPLAYABLE_ERROR":
                return GenerationStatus(
                    task_id="",
                    status="failed",
                    error=str(e),
                    error_code=str(e.rpc_code) if e.rpc_code is not None else None,
                )
            raise

    async def _list_raw(self, notebook_id: str) -> builtins.list[Any]:
        """Get raw artifact list data."""
        params = [[2], notebook_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"']
        result = await self._core.rpc_call(
            RPCMethod.LIST_ARTIFACTS,
            params,
            source_path=f"/notebook/{notebook_id}",
            allow_null=True,
        )
        if not result or not isinstance(result, list):
            return []

        first = result[0]
        if len(result) == 1 and isinstance(first, list):
            if not first:
                return []
            if isinstance(first[0], list):
                return first

        return result

    def _parse_generation_result(self, result: Any) -> GenerationStatus:
        """Parse generation API result into GenerationStatus."""
        if result and isinstance(result, list) and len(result) > 0:
            artifact_data = result[0]
            artifact_id = (
                artifact_data[0]
                if isinstance(artifact_data, list) and len(artifact_data) > 0
                else None
            )
            status_code = (
                artifact_data[4]
                if isinstance(artifact_data, list) and len(artifact_data) > 4
                else None
            )

            if artifact_id:
                status = (
                    artifact_status_to_str(status_code) if status_code is not None else "pending"
                )
                return GenerationStatus(task_id=artifact_id, status=status)

        return GenerationStatus(
            task_id="",
            status="failed",
            error="Generation failed - no artifact_id returned",
        )

    def _get_artifact_type_name(self, artifact_type: int) -> str:
        """Get a human-readable artifact type name."""
        try:
            return ArtifactTypeCode(artifact_type).name
        except ValueError:
            return str(artifact_type)

    def _is_media_ready(self, art: builtins.list[Any], artifact_type: int) -> bool:
        """Check if an artifact has the completion data required by the MVP."""
        if artifact_type != ArtifactTypeCode.AUDIO.value:
            return True

        try:
            if len(art) > 6 and isinstance(art[6], list) and len(art[6]) > 5:
                media_list = art[6][5]
                if isinstance(media_list, list) and media_list:
                    first_item = media_list[0]
                    return isinstance(first_item, list) and bool(first_item) and isinstance(
                        first_item[0], str
                    )
            return False
        except (IndexError, TypeError) as e:
            logger.debug("Unexpected audio artifact structure while polling: %s", e)
            return False
