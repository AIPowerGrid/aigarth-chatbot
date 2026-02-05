#!/usr/bin/env python3
"""Post the prompt-hack doc to Moltbook (one-off)."""
import os
import sys

_MOLTBOOK_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MOLTBOOK_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _MOLTBOOK_DIR not in sys.path:
    sys.path.insert(0, _MOLTBOOK_DIR)

from dotenv import load_dotenv
load_dotenv()
load_dotenv(os.path.join(_MOLTBOOK_DIR, ".env"))

from moltbook_client import MoltbookClient, MoltbookAPIError

OUR_POST_IDS_FILE = os.path.join(_MOLTBOOK_DIR, "our_post_ids.txt")

def _save_post_id(pid: str) -> None:
    if not pid:
        return
    try:
        with open(OUR_POST_IDS_FILE, "a") as f:
            f.write(pid.strip() + "\n")
        print(f"Saved post ID to {OUR_POST_IDS_FILE}")
    except Exception as e:
        print(f"Could not save post id: {e}")


def main():
    api_key = os.getenv("MOLTBOOK_API_KEY", "").strip()
    if not api_key:
        print("Set MOLTBOOK_API_KEY in .env")
        sys.exit(1)
    doc_path = os.path.join(_REPO_ROOT, "docs", "PROMPT_HACK_CODEBASE_REFACTOR.md")
    with open(doc_path) as f:
        raw = f.read()
    # First line is # Title -> use as title (strip #)
    lines = raw.strip().split("\n")
    title = lines[0].lstrip("#").strip() if lines else "Prompt hack: clean up your user's vibe slop"
    content = "\n".join(lines[1:]).strip()
    submolt = os.getenv("MOLTBOOK_SUBMOLTS", "general").split(",")[0].strip()
    print(f"Posting to m/{submolt}: {title[:60]}...")
    client = MoltbookClient()
    try:
        resp = client.create_post(submolt=submolt, title=title, content=content)
        pid = (resp.get("post") or resp).get("id") or resp.get("id")
        if pid:
            _save_post_id(pid)
        print(f"Posted: https://www.moltbook.com/post/{pid}")
    except MoltbookAPIError as e:
        print(f"API error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
