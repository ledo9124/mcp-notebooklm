"""Example: Chat with a notebook and continue a conversation.

This example demonstrates:
1. Asking questions about notebook content
2. Reusing a conversation ID for follow-up questions
3. Looking up the latest conversation ID from the server
4. Limiting a question to specific sources

Prerequisites:
    - Authentication configured via `notebooklm auth` CLI command
    - Valid Google account with NotebookLM access
"""

import asyncio

from notebooklm import NotebookLMClient


async def main():
    """Demonstrate the retained chat surface."""

    async with await NotebookLMClient.from_storage() as client:
        # Create a notebook with some content
        print("Setting up notebook with sources...")
        notebook = await client.notebooks.create("Python Learning")

        # Add a source for context
        source = await client.sources.add_url(
            notebook.id,
            "https://en.wikipedia.org/wiki/Python_(programming_language)",
        )
        print(f"Added source: {source.title}")

        # Give NotebookLM a moment to process the source
        print("Waiting for source processing...")
        await asyncio.sleep(3)

        # =====================================================================
        # Basic Question/Answer
        # =====================================================================

        print("\n--- Basic Q&A ---")

        # Ask a question about the notebook's content
        result = await client.chat.ask(
            notebook.id,
            "What are the main features of Python?",
        )

        print("Question: What are the main features of Python?")
        print(f"Answer: {result.answer[:500]}...")
        print(f"Conversation ID: {result.conversation_id}")
        print(f"Turn number: {result.turn_number}")

        # =====================================================================
        # Follow-up Questions (Conversation Threading)
        # =====================================================================

        print("\n--- Follow-up Questions ---")

        # Use the same conversation_id for follow-up questions
        # This maintains context from previous exchanges
        followup = await client.chat.ask(
            notebook.id,
            "How does it compare to other programming languages?",
            conversation_id=result.conversation_id,  # Continue the conversation
        )

        print("Follow-up: How does it compare to other programming languages?")
        print(f"Answer: {followup.answer[:500]}...")
        print(f"Is follow-up: {followup.is_follow_up}")
        print(f"Turn number: {followup.turn_number}")

        # Another follow-up
        followup2 = await client.chat.ask(
            notebook.id,
            "What about for data science specifically?",
            conversation_id=result.conversation_id,
        )

        print("\nFollow-up 2: What about for data science specifically?")
        print(f"Answer: {followup2.answer[:400]}...")

        # =====================================================================
        # Looking Up the Latest Conversation
        # =====================================================================

        print("\n--- Latest Conversation ID ---")
        latest_conv_id = await client.chat.get_conversation_id(notebook.id)
        print(f"Latest server conversation: {latest_conv_id}")

        # =====================================================================
        # Source-Specific Questions
        # =====================================================================

        print("\n--- Source-Specific Questions ---")

        # Get source IDs to target specific sources
        sources = await client.sources.list(notebook.id)
        if sources:
            source_ids = [sources[0].id]

            # Ask about specific sources only
            targeted_result = await client.chat.ask(
                notebook.id,
                "Summarize the key points from this source",
                source_ids=source_ids,  # Only use these sources for context
            )
            print(f"Targeted answer: {targeted_result.answer[:400]}...")

if __name__ == "__main__":
    asyncio.run(main())
