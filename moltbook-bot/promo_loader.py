"""
Load promo/ad posts from a simple markdown file.
Format: blocks separated by ---; each block has optional submolt:, title:, then body.
"""
import os
import re
from typing import List, Dict, Any

# Default path relative to this file
DEFAULT_PROMO_PATH = os.path.join(os.path.dirname(__file__), "promo_posts.md")


def load_promo_posts(path: str = DEFAULT_PROMO_PATH) -> List[Dict[str, Any]]:
    """Load list of {submolt, title, content} from promo_posts.md."""
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    posts = []
    for block in re.split(r"\n---+\n", text):
        block = block.strip()
        if not block:
            continue
        submolt = None
        title = None
        lines = block.split("\n")
        body_lines = []
        for line in lines:
            if line.startswith("submolt:"):
                submolt = line.split(":", 1)[1].strip()
            elif line.startswith("title:"):
                title = line.split(":", 1)[1].strip()
            else:
                body_lines.append(line)
        content = "\n".join(body_lines).strip()
        if not content and not title:
            continue
        if not title:
            title = (content[:80] + "…") if len(content) > 80 else content
        posts.append({
            "submolt": submolt,
            "title": title,
            "content": content or "",
        })
    return posts
