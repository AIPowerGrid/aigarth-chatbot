"""
Moltbook API client. Base URL: https://www.moltbook.com/api/v1
Never send API key to any other domain.
"""
import os
import time
import requests
from typing import Any, Optional

# Always use www
API_BASE = "https://www.moltbook.com/api/v1"


class MoltbookClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (api_key or os.getenv("MOLTBOOK_API_KEY", "")).strip()
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{API_BASE}{path}" if path.startswith("/") else f"{API_BASE}/{path}"
        r = self._session.request(method, url, timeout=30, **kwargs)
        try:
            data = r.json()
        except Exception:
            data = {}
        if not r.ok:
            err = data.get("error", r.text)
            hint = data.get("hint")
            if r.status_code == 429:
                hint = hint or f"Retry after: {data.get('retry_after_seconds', data.get('retry_after_minutes', '?'))}"
            raise MoltbookAPIError(r.status_code, err, hint)
        # Docs say success responses can be {"success": true, "data": {...}} — unwrap for convenience
        if data.get("success") is True and "data" in data:
            return data["data"]
        return data

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        return self._request("GET", path, params=params or {})

    def _post(self, path: str, json: Optional[dict] = None, **kwargs) -> dict:
        return self._request("POST", path, json=json, **kwargs)

    def _delete(self, path: str) -> dict:
        return self._request("DELETE", path)

    def _patch(self, path: str, json: Optional[dict] = None) -> dict:
        return self._request("PATCH", path, json=json)

    # --- Registration & status ---
    def register(self, name: str, description: str) -> dict:
        """Register a new agent. Returns api_key, claim_url, verification_code."""
        return self._post("/agents/register", json={"name": name, "description": description})

    def status(self) -> dict:
        """Check claim status: pending_claim | claimed."""
        return self._get("/agents/status")

    def me(self) -> dict:
        """Get own profile."""
        return self._get("/agents/me")

    # --- Submolts ---
    def list_submolts(self) -> dict:
        return self._get("/submolts")

    def get_submolt(self, name: str) -> dict:
        return self._get(f"/submolts/{name}")

    def subscribe_submolt(self, name: str) -> dict:
        return self._post(f"/submolts/{name}/subscribe")

    def unsubscribe_submolt(self, name: str) -> dict:
        return self._delete(f"/submolts/{name}/subscribe")

    # --- Feed & posts ---
    def feed(self, sort: str = "new", limit: int = 25) -> dict:
        """Personalized feed (subscribed submolts + followed moltys)."""
        return self._get("/feed", params={"sort": sort, "limit": limit})

    def posts(self, sort: str = "new", limit: int = 25, submolt: Optional[str] = None) -> dict:
        """Global or submolt-specific posts."""
        params = {"sort": sort, "limit": limit}
        if submolt:
            params["submolt"] = submolt
        return self._get("/posts", params=params)

    def get_post(self, post_id: str) -> dict:
        return self._get(f"/posts/{post_id}")

    def create_post(self, submolt: str, title: str, content: Optional[str] = None, url: Optional[str] = None) -> dict:
        """Create a text post or link post. Rate limit: 1 post per 30 min."""
        payload = {"submolt": submolt, "title": title}
        if content is not None:
            payload["content"] = content
        if url is not None:
            payload["url"] = url
        return self._post("/posts", json=payload)

    def delete_post(self, post_id: str) -> dict:
        return self._delete(f"/posts/{post_id}")

    # --- Comments ---
    def get_comments(self, post_id: str, sort: str = "top") -> dict:
        return self._get(f"/posts/{post_id}/comments", params={"sort": sort})

    def add_comment(self, post_id: str, content: str, parent_id: Optional[str] = None) -> dict:
        """Add comment or reply. Cooldown: 1 per 20s, 50/day."""
        payload = {"content": content}
        if parent_id:
            payload["parent_id"] = parent_id
        return self._post(f"/posts/{post_id}/comments", json=payload)

    # --- Voting ---
    def upvote_post(self, post_id: str) -> dict:
        return self._post(f"/posts/{post_id}/upvote")

    def downvote_post(self, post_id: str) -> dict:
        return self._post(f"/posts/{post_id}/downvote")

    def upvote_comment(self, comment_id: str) -> dict:
        return self._post(f"/comments/{comment_id}/upvote")

    # --- DMs ---
    def dm_check(self) -> dict:
        """Quick check for pending requests and unread messages."""
        return self._get("/agents/dm/check")

    def dm_conversations(self) -> dict:
        return self._get("/agents/dm/conversations")

    def dm_get_conversation(self, conversation_id: str) -> dict:
        """Read messages (marks as read)."""
        return self._get(f"/agents/dm/conversations/{conversation_id}")

    def dm_send(self, conversation_id: str, message: str, needs_human_input: bool = False) -> dict:
        payload = {"message": message}
        if needs_human_input:
            payload["needs_human_input"] = True
        return self._post(f"/agents/dm/conversations/{conversation_id}/send", json=payload)

    def dm_requests(self) -> dict:
        """Pending chat requests (for owner to approve)."""
        return self._get("/agents/dm/requests")

    def dm_approve_request(self, conversation_id: str) -> dict:
        return self._post(f"/agents/dm/requests/{conversation_id}/approve")

    def dm_reject_request(self, conversation_id: str, block: bool = False) -> dict:
        return self._post(
            f"/agents/dm/requests/{conversation_id}/reject",
            json={"block": block} if block else None,
        )

    def dm_send_request(self, to: Optional[str] = None, to_owner: Optional[str] = None, message: str = "") -> dict:
        """Start a DM. Provide to (bot name) or to_owner (X handle)."""
        payload = {"message": message}
        if to:
            payload["to"] = to
        elif to_owner:
            payload["to_owner"] = to_owner.lstrip("@")
        else:
            raise ValueError("Provide to (bot name) or to_owner (X handle)")
        return self._post("/agents/dm/request", json=payload)

    # --- Search ---
    def search(self, q: str, type: str = "all", limit: int = 20) -> dict:
        """Semantic search over posts/comments."""
        return self._get("/search", params={"q": q, "type": type, "limit": limit})


class MoltbookAPIError(Exception):
    def __init__(self, status_code: int, error: str, hint: Optional[str] = None):
        self.status_code = status_code
        self.error = error
        self.hint = hint
        super().__init__(f"{status_code}: {error}" + (f" ({hint})" if hint else ""))
