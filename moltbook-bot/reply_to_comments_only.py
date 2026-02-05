#!/usr/bin/env python3
"""
Reply only to comments on our posts (no DMs, no feed). Use when you want to
clear a backlog or after you tell the bot to "reply to comments".
From repo root: venv/bin/python moltbook-bot/reply_to_comments_only.py
"""
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

import importlib.util
_spec = importlib.util.spec_from_file_location("moltbook_bot", os.path.join(_MOLTBOOK_DIR, "bot.py"))
_mb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mb)

def main():
    if not os.getenv("MOLTBOOK_API_KEY", "").strip():
        print("Set MOLTBOOK_API_KEY in .env")
        sys.exit(1)
    client = MoltbookClient()
    retriever = DocumentRetriever()
    grid = GridClient()
    print("Replying only to comments on our posts (see engagement.log for details)…")
    n, _ = asyncio.run(_mb.reply_to_comments_on_our_posts(client, grid, retriever))
    print(f"Done. Replied to {n} comment(s).")

if __name__ == "__main__":
    main()
