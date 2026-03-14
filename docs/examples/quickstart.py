#!/usr/bin/env python3
"""Quickstart example for notebooklm-py.

This script demonstrates the active MVP workflow:
1. Create a notebook
2. Add sources
3. Chat with content
4. Generate an audio overview
5. Reuse the completion URL

Prerequisites:
    pip install "notebooklm-py[browser]"
    playwright install chromium
    notebooklm login  # Authenticate first

Usage:
    python quickstart.py
"""

import asyncio

from notebooklm import NotebookLMClient


async def main():
    print("=== NotebookLM Quickstart ===\n")

    async with await NotebookLMClient.from_storage() as client:
        # 1. Create a notebook
        print("Creating notebook...")
        nb = await client.notebooks.create("Quickstart Demo")
        print(f"  Created: {nb.id} - {nb.title}\n")

        # 2. Add a source
        print("Adding source...")
        url = "https://en.wikipedia.org/wiki/Artificial_intelligence"
        source = await client.sources.add_url(nb.id, url)
        print(f"  Added: {source.title}\n")

        # 3. Chat with the content
        print("Asking a question...")
        result = await client.chat.ask(nb.id, "What are the main topics covered?")
        print(f"  Answer: {result.answer[:200]}...\n")

        # 3b. Continue the conversation
        follow_up = await client.chat.ask(
            nb.id,
            "Continue that summary with the most important milestones.",
            conversation_id=result.conversation_id,
        )
        print(f"  Follow-up: {follow_up.answer[:200]}...\n")

        # 4. Generate an audio overview
        print("Generating podcast (this may take a few minutes)...")
        status = await client.artifacts.generate_audio(
            nb.id, instructions="Focus on the key milestones"
        )
        print(f"  Started generation, task_id: {status.task_id}")

        # Wait for completion
        final = await client.artifacts.wait_for_completion(
            nb.id, status.task_id, timeout=300, poll_interval=10
        )

        if final.is_complete:
            print(f"  Complete! URL: {final.url}\n")
            print("  Download helpers are outside the active MVP on this branch.")
            print("  Use the returned URL or the NotebookLM web UI if you need a local copy.\n")
        else:
            print(f"  Generation status: {final.status}\n")

        print(f"Notebook retained for follow-up work: {nb.id}\n")

    print("=== Done! ===")


if __name__ == "__main__":
    asyncio.run(main())
