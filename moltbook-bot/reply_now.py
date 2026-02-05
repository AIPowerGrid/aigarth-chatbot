#!/usr/bin/env python3
"""Run one cycle of the Moltbook bot: DMs + reply to comments on our posts. Use when people are waiting."""
import os
import sys
import asyncio

_MOLTBOOK_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MOLTBOOK_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _MOLTBOOK_DIR not in sys.path:
    sys.path.insert(0, _MOLTBOOK_DIR)

from dotenv import load_dotenv
load_dotenv()
load_dotenv(os.path.join(_MOLTBOOK_DIR, ".env"))

from moltbook_client import MoltbookClient
from retriever import DocumentRetriever
from grid_client import GridClient

# Import from moltbook-bot/bot.py (not repo root bot.py)
import importlib.util
_spec = importlib.util.spec_from_file_location("moltbook_bot", os.path.join(_MOLTBOOK_DIR, "bot.py"))
_mb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mb)
run_cycle = _mb.run_cycle

def main():
    if not os.getenv("MOLTBOOK_API_KEY", "").strip():
        print("Set MOLTBOOK_API_KEY in .env")
        sys.exit(1)
    client = MoltbookClient()
    retriever = DocumentRetriever()
    grid = GridClient()
    print("Running one cycle: DMs + comment replies…")
    asyncio.run(run_cycle(client, retriever, grid))
    print("Done.")

if __name__ == "__main__":
    main()
