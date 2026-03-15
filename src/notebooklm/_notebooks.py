"""Notebook operations API."""

import logging
from typing import Any

from ._core import ClientCore
from .rpc import RPCMethod
from .types import Notebook, NotebookDescription, SuggestedTopic

logger = logging.getLogger(__name__)


def _parse_get_notebook_result(result: Any) -> Notebook:
    """Parse the GET_NOTEBOOK RPC response into a Notebook dataclass."""
    nb_info = result[0] if result and isinstance(result, list) and len(result) > 0 else []
    return Notebook.from_api_response(nb_info)


async def _delete_notebook_rpc(core: ClientCore, notebook_id: str) -> bool:
    """Legacy/internal helper for notebook deletion outside the MVP SDK surface."""
    logger.debug("Deleting notebook: %s", notebook_id)
    params = [[notebook_id], [2]]
    await core.rpc_call(RPCMethod.DELETE_NOTEBOOK, params)
    return True


async def _rename_notebook_rpc(core: ClientCore, notebook_id: str, new_title: str) -> Notebook:
    """Legacy/internal helper for notebook rename outside the MVP SDK surface."""
    logger.debug("Renaming notebook %s to: %s", notebook_id, new_title)
    params = [notebook_id, [[None, None, None, [None, new_title]]]]
    await core.rpc_call(
        RPCMethod.RENAME_NOTEBOOK,
        params,
        source_path="/",
        allow_null=True,
    )
    result = await core.rpc_call(
        RPCMethod.GET_NOTEBOOK,
        [notebook_id, None, [2], None, 0],
        source_path=f"/notebook/{notebook_id}",
    )
    return _parse_get_notebook_result(result)


class NotebooksAPI:
    """Operations on NotebookLM notebooks.

    Provides the minimal notebook surface kept in the MVP:
    list, create, get, summarize, and raw inspection helpers.

    Usage:
        async with NotebookLMClient.from_storage() as client:
            notebooks = await client.notebooks.list()
            new_nb = await client.notebooks.create("My Research")
            desc = await client.notebooks.get_description(new_nb.id)
    """

    def __init__(self, core: ClientCore):
        """Initialize the notebooks API.

        Args:
            core: The core client infrastructure.
        """
        self._core = core

    async def list(self) -> list[Notebook]:
        """List all notebooks.

        Returns:
            List of Notebook objects.
        """
        logger.debug("Listing notebooks")
        params = [None, 1, None, [2]]
        result = await self._core.rpc_call(RPCMethod.LIST_NOTEBOOKS, params)

        if result and isinstance(result, list) and len(result) > 0:
            raw_notebooks = result[0] if isinstance(result[0], list) else result
            return [Notebook.from_api_response(nb) for nb in raw_notebooks]
        return []

    async def create(self, title: str) -> Notebook:
        """Create a new notebook.

        Args:
            title: The title for the new notebook.

        Returns:
            The created Notebook object.
        """
        logger.debug("Creating notebook: %s", title)
        params = [title, None, None, [2], [1]]
        result = await self._core.rpc_call(RPCMethod.CREATE_NOTEBOOK, params)
        notebook = Notebook.from_api_response(result)
        logger.debug("Created notebook: %s", notebook.id)
        return notebook

    async def delete(self, notebook_id: str) -> bool:
        """Delete one notebook."""
        return await _delete_notebook_rpc(self._core, notebook_id)

    async def get(self, notebook_id: str) -> Notebook:
        """Get notebook details.

        Args:
            notebook_id: The notebook ID.

        Returns:
            Notebook object with details.
        """
        params = [notebook_id, None, [2], None, 0]
        result = await self._core.rpc_call(
            RPCMethod.GET_NOTEBOOK,
            params,
            source_path=f"/notebook/{notebook_id}",
        )
        return _parse_get_notebook_result(result)

    async def get_summary(self, notebook_id: str) -> str:
        """Get raw summary text for a notebook.

        For parsed summary with topics, use get_description() instead.

        Args:
            notebook_id: The notebook ID.

        Returns:
            Raw summary text string.
        """
        params = [notebook_id, [2]]
        result = await self._core.rpc_call(
            RPCMethod.SUMMARIZE,
            params,
            source_path=f"/notebook/{notebook_id}",
        )
        if result and isinstance(result, list) and len(result) > 0:
            return str(result[0]) if result[0] else ""
        return ""

    async def get_description(self, notebook_id: str) -> NotebookDescription:
        """Get AI-generated summary and suggested topics for a notebook.

        This provides a high-level overview of what the notebook contains,
        similar to what's shown in the Chat panel when opening a notebook.

        Args:
            notebook_id: The notebook ID.

        Returns:
            NotebookDescription with summary and suggested topics.

        Example:
            desc = await client.notebooks.get_description(notebook_id)
            print(desc.summary)
            for topic in desc.suggested_topics:
                print(f"Q: {topic.question}")
        """
        # Get raw summary data
        params = [notebook_id, [2]]
        result = await self._core.rpc_call(
            RPCMethod.SUMMARIZE,
            params,
            source_path=f"/notebook/{notebook_id}",
        )

        summary = ""
        suggested_topics: list[SuggestedTopic] = []

        if result and isinstance(result, list):
            # Summary at [0][0]
            if len(result) > 0 and isinstance(result[0], list) and len(result[0]) > 0:
                summary = result[0][0] if isinstance(result[0][0], str) else ""

            # Suggested topics at [1][0]
            if len(result) > 1 and isinstance(result[1], list) and len(result[1]) > 0:
                topics_list = result[1][0] if isinstance(result[1][0], list) else []
                for topic in topics_list:
                    if isinstance(topic, list) and len(topic) >= 2:
                        suggested_topics.append(
                            SuggestedTopic(
                                question=topic[0] if isinstance(topic[0], str) else "",
                                prompt=topic[1] if isinstance(topic[1], str) else "",
                            )
                        )

        return NotebookDescription(summary=summary, suggested_topics=suggested_topics)

    async def get_raw(self, notebook_id: str) -> Any:
        """Get raw notebook data from API.

        This returns the raw API response, useful for accessing data
        not parsed into the Notebook dataclass (like sources list).

        Args:
            notebook_id: The notebook ID.

        Returns:
            Raw API response data.
        """
        params = [notebook_id, None, [2], None, 0]
        return await self._core.rpc_call(
            RPCMethod.GET_NOTEBOOK,
            params,
            source_path=f"/notebook/{notebook_id}",
        )
