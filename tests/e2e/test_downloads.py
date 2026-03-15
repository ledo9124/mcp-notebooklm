import os
import tempfile

import pytest

from notebooklm.exceptions import ValidationError

from .conftest import requires_auth

_UNUSED_NOTEBOOK_ID = "nb_mvp_unsupported"
_UNSUPPORTED_MATCH = "is not supported on this branch"


@requires_auth
class TestUnsupportedArtifactDownloads:
    @pytest.mark.asyncio
    @pytest.mark.readonly
    @pytest.mark.parametrize(
        ("method_name", "output_name"),
        [
            ("download_audio", "audio.mp4"),
            ("download_video", "video.mp4"),
            ("download_infographic", "infographic.png"),
            ("download_slide_deck", "slides.pdf"),
            ("download_report", "report.md"),
            ("download_mind_map", "mindmap.json"),
            ("download_data_table", "data.csv"),
        ],
    )
    async def test_download_surface_rejected_on_mvp_branch(
        self,
        client,
        method_name,
        output_name,
    ):
        """Unsupported download surfaces should fail fast on the MVP branch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, output_name)
            method = getattr(client.artifacts, method_name)
            with pytest.raises(ValidationError, match=_UNSUPPORTED_MATCH):
                await method(_UNUSED_NOTEBOOK_ID, output_path)


@requires_auth
class TestUnsupportedArtifactExport:
    @pytest.mark.asyncio
    @pytest.mark.readonly
    async def test_export_artifact_rejected_on_mvp_branch(self, client):
        """Generic export is intentionally pruned from the active MVP."""
        with pytest.raises(ValidationError, match=_UNSUPPORTED_MATCH):
            await client.artifacts.export(_UNUSED_NOTEBOOK_ID, artifact_id="art_mvp_unsupported")
