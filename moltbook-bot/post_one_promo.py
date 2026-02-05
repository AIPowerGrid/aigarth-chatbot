#!/usr/bin/env python3
"""
Post a single promo to Moltbook (bypasses the 30-min loop).
Usage (from repo root):
  python moltbook-bot/post_one_promo.py           # post last promo (the long "what we do" one)
  python moltbook-bot/post_one_promo.py 0         # post first promo
  python moltbook-bot/post_one_promo.py 4         # post promo at index 4
"""
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
from promo_loader import load_promo_posts

# Same save logic as bot.py so this post gets comment replies
OUR_POST_IDS_FILE = os.path.join(_MOLTBOOK_DIR, "our_post_ids.txt")

def _save_post_id(pid: str) -> None:
    if not pid:
        return
    try:
        with open(OUR_POST_IDS_FILE, "a") as f:
            f.write(pid.strip() + "\n")
        print(f"Saved post ID to {OUR_POST_IDS_FILE} (bot will reply to comments on it)")
    except Exception as e:
        print(f"Could not save post id: {e}")


def main():
    api_key = os.getenv("MOLTBOOK_API_KEY", "").strip()
    if not api_key:
        print("Set MOLTBOOK_API_KEY in .env")
        sys.exit(1)
    posts = load_promo_posts()
    if not posts:
        print("No promos in promo_posts.md")
        sys.exit(1)
    index = 0
    if len(sys.argv) > 1:
        try:
            index = int(sys.argv[1])
        except ValueError:
            index = 0
    index = index % len(posts)
    promo = posts[index]
    submolt = promo.get("submolt") or os.getenv("MOLTBOOK_SUBMOLTS", "general").split(",")[0].strip()
    title = promo.get("title") or "AI Power Grid"
    content = promo.get("content") or ""
    print(f"Posting promo #{index} to m/{submolt}: {title[:60]}...")
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
