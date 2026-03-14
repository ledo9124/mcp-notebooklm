import pytest

from notebooklm import Notebook, NotebookDescription

from .conftest import requires_auth


@requires_auth
class TestNotebookOperations:
    @pytest.mark.asyncio
    async def test_list_notebooks(self, client):
        notebooks = await client.notebooks.list()
        assert isinstance(notebooks, list)
        assert all(isinstance(nb, Notebook) for nb in notebooks)

    @pytest.mark.asyncio
    async def test_get_notebook(self, client, read_only_notebook_id):
        notebook = await client.notebooks.get(read_only_notebook_id)
        assert notebook is not None
        assert isinstance(notebook, Notebook)
        assert notebook.id == read_only_notebook_id

    @pytest.mark.asyncio
    async def test_create_notebook(self, client, created_notebooks, cleanup_notebooks):
        notebook = await client.notebooks.create("E2E Test Notebook")
        assert isinstance(notebook, Notebook)
        assert notebook.title == "E2E Test Notebook"
        created_notebooks.append(notebook.id)

        fetched = await client.notebooks.get(notebook.id)
        assert fetched.id == notebook.id
        assert fetched.title == notebook.title

@requires_auth
class TestNotebookAsk:
    @pytest.mark.asyncio
    async def test_ask_notebook(self, client, read_only_notebook_id):
        result = await client.chat.ask(read_only_notebook_id, "What is this notebook about?")
        assert result.answer is not None
        assert result.conversation_id is not None


@requires_auth
class TestNotebookDescription:
    @pytest.mark.asyncio
    async def test_get_description(self, client, read_only_notebook_id):
        description = await client.notebooks.get_description(read_only_notebook_id)

        assert isinstance(description, NotebookDescription)
        assert description.summary is not None
        assert isinstance(description.suggested_topics, list)
@requires_auth
class TestNotebookSummary:
    """Tests for notebook summary operations."""

    @pytest.mark.asyncio
    @pytest.mark.readonly
    async def test_get_summary(self, client, read_only_notebook_id):
        """Test getting notebook summary."""
        summary = await client.notebooks.get_summary(read_only_notebook_id)
        # Summary may be empty string if not generated yet
        assert isinstance(summary, str)

    @pytest.mark.asyncio
    @pytest.mark.readonly
    async def test_get_raw(self, client, read_only_notebook_id):
        """Test getting raw notebook data."""
        raw_data = await client.notebooks.get_raw(read_only_notebook_id)
        assert raw_data is not None
        # Raw data is typically a list with notebook structure
        assert isinstance(raw_data, list)
