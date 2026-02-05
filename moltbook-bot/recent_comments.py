#!/usr/bin/env python3
"""Fetch and print recent comments on our Moltbook posts. Run from repo root."""
import os
import sys
from datetime import datetime

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


def load_post_ids():
    env_ids = os.getenv("MOLTBOOK_OUR_POST_IDS", "").strip()
    ids = [x.strip() for x in env_ids.split(",") if x.strip()]
    if os.path.isfile(OUR_POST_IDS_FILE):
        with open(OUR_POST_IDS_FILE, "r") as f:
            ids.extend(line.strip() for line in f if line.strip())
    return ids


def main():
    if not os.getenv("MOLTBOOK_API_KEY", "").strip():
        print("Set MOLTBOOK_API_KEY in .env")
        sys.exit(1)
    client = MoltbookClient()
    post_ids = load_post_ids()
    if not post_ids:
        print("No post IDs in MOLTBOOK_OUR_POST_IDS or our_post_ids.txt")
        sys.exit(0)
    print(f"Checking {len(post_ids)} post(s) for recent comments…\n")
    for post_id in post_ids:
        try:
            resp = client.get_post(post_id)
        except MoltbookAPIError as e:
            print(f"Post {post_id}: API error {e}\n")
            continue
        post_obj = resp.get("post") or resp
        title = (post_obj.get("title") or "")[:60] if isinstance(post_obj, dict) else ""
        url = f"https://www.moltbook.com/post/{post_id}"
        print(f"Post: {title or post_id}")
        print(f"URL:  {url}")
        try:
            comments_resp = client.get_comments(post_id, sort="new")
        except MoltbookAPIError as e:
            print(f"Comments: API error {e}\n")
            continue
        raw = comments_resp.get("comments") or comments_resp.get("items") or comments_resp.get("data")
        if isinstance(raw, dict):
            raw = raw.get("items") or raw.get("comments") or []
        comments = raw if isinstance(raw, list) else []
        if not comments:
            print("Comments: (none)\n")
            continue
        print(f"Comments: {len(comments)}\n")
        for c in comments[:25]:
            author = (c.get("author") or c.get("user") or {}) if isinstance(c, dict) else {}
            name = (author.get("name") or author.get("username") or "?") if isinstance(author, dict) else "?"
            body = (c.get("content") or c.get("body") or c.get("text") or c.get("message") or "")[:300]
            created = c.get("created_at") or c.get("timestamp") or ""
            print(f"  • {name}: {body}")
            if created:
                print(f"    {created}")
        print()


if __name__ == "__main__":
    main()
