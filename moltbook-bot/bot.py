"""
Moltbook bot: subscribes to submolts, responds to DMs with RAG, comments on feed, posts promos.
Run from repo root: python moltbook-bot/bot.py
"""
import json
import os
import sys
import asyncio
import time
from datetime import datetime

# Run from repo root so we can import shared modules
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MOLTBOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _MOLTBOOK_DIR not in sys.path:
    sys.path.insert(0, _MOLTBOOK_DIR)

from dotenv import load_dotenv
load_dotenv()
load_dotenv(os.path.join(_MOLTBOOK_DIR, ".env"))

from moltbook_client import MoltbookClient, MoltbookAPIError
from promo_loader import load_promo_posts

# Shared RAG + Grid (from repo root)
from retriever import DocumentRetriever
from grid_client import GridClient

# Config
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY", "").strip()
POLL_INTERVAL_SEC = max(60, int(os.getenv("MOLTBOOK_POLL_INTERVAL", "300")))   # min 60s for monitoring/replies
FEED_SORT = os.getenv("MOLTBOOK_FEED_SORT", "new")
FEED_LIMIT = int(os.getenv("MOLTBOOK_FEED_LIMIT", "15"))
# Comma-separated submolts to subscribe to (and read feed from)
SUBMOLTS_STR = os.getenv("MOLTBOOK_SUBMOLTS", "general")
# Where to post promos (default: same as subscribe list)
AD_SUBMOLTS_STR = os.getenv("MOLTBOOK_AD_SUBMOLTS", "").strip() or SUBMOLTS_STR
# Optional: only post promos to these "top" submolts (comma list). If set, we restrict to this list.
TOP_SUBMOLTS_STR = os.getenv("MOLTBOOK_TOP_SUBMOLTS", "").strip()
# Post one promo at most every 30 min (Moltbook limit)
PROMO_COOLDOWN_SEC = 30 * 60
# Comment cooldown 20s
COMMENT_COOLDOWN_SEC = 20
# Set to 0 to only do DMs + promos (no commenting on feed)
COMMENT_ON_FEED = os.getenv("MOLTBOOK_COMMENT_ON_FEED", "1") == "1"
# Explicit post IDs to always check for comments (optional; we also auto-save IDs when we post)
OUR_POST_IDS_STR = os.getenv("MOLTBOOK_OUR_POST_IDS", "").strip()
OUR_POST_IDS_FILE = os.path.join(_MOLTBOOK_DIR, "our_post_ids.txt")
# Debug logging for comment reply and API response shape
DEBUG = os.getenv("MOLTBOOK_DEBUG", "").lower() in ("1", "true", "yes")
# Engagement log (append-only); tail this to see comments, DMs, replies
ENGAGEMENT_LOG = os.path.join(_MOLTBOOK_DIR, "engagement.log")


def _log_engagement(msg: str) -> None:
    """Append a timestamped line to engagement.log (for tail / review)."""
    try:
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(ENGAGEMENT_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
            f.flush()
    except Exception:
        pass


def _load_our_post_ids() -> list[str]:
    """IDs we've saved (e.g. from posts we created). One UUID per line."""
    if not os.path.isfile(OUR_POST_IDS_FILE):
        return []
    try:
        with open(OUR_POST_IDS_FILE, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []


def _save_post_id(pid: str) -> None:
    """Append a post ID so we always check it for comments."""
    if not pid:
        return
    try:
        with open(OUR_POST_IDS_FILE, "a") as f:
            f.write(pid.strip() + "\n")
    except Exception as e:
        print(f"  Could not save post id to {OUR_POST_IDS_FILE}: {e}")


def parse_list(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]

SUBMOLT_LIST = parse_list(SUBMOLTS_STR)
AD_SUBMOLT_LIST = parse_list(AD_SUBMOLTS_STR)
TOP_SUBMOLT_LIST = parse_list(TOP_SUBMOLTS_STR)
OUR_POST_IDS = parse_list(OUR_POST_IDS_STR)

# State
last_promo_post_time: float = 0
last_comment_time: float = 0
last_seen_post_ids: set = set()
replied_comment_ids: set = set()
upvoted_post_ids: set = set()
promo_index: int = 0


def ensure_subscriptions(client: MoltbookClient):
    """Subscribe to configured submolts if not already."""
    for submolt in SUBMOLT_LIST:
        try:
            client.subscribe_submolt(submolt)
            print(f"  Subscribed to m/{submolt}")
        except MoltbookAPIError as e:
            if e.status_code == 429:
                print(f"  Rate limited subscribing to m/{submolt}, will retry later")
            else:
                print(f"  Could not subscribe to m/{submolt}: {e}")


async def handle_dm_activity(client: MoltbookClient, retriever: DocumentRetriever, grid: GridClient):
    """Check DMs, reply to unread with RAG + Grid."""
    try:
        check = client.dm_check()
    except MoltbookAPIError as e:
        print(f"  DM check failed: {e}")
        return
    if not check.get("has_activity"):
        return
    summary = check.get("summary", "")
    _log_engagement(f"DM: {summary}")
    print(f"  DM activity: {summary}")
    # Pending requests: we don't auto-approve; log only
    reqs = check.get("requests", {}) or {}
    if reqs.get("count", 0) > 0:
        for item in reqs.get("items", []):
            who = item.get("from", {}).get("name", "?")
            prev = (item.get("message_preview") or "")[:80]
            _log_engagement(f"DM: PENDING request from {who}: {prev}")
            print(f"  [PENDING REQUEST] from {who}: {prev}")
    # Unread messages: list conversations and reply
    try:
        inbox = client.dm_conversations()
    except MoltbookAPIError as e:
        print(f"  Conversations list failed: {e}")
        return
    convs = (inbox.get("conversations") or {}).get("items") or []
    for c in convs:
        if c.get("unread_count", 0) == 0:
            continue
        cid = c.get("conversation_id")
        if not cid:
            continue
        try:
            conv = client.dm_get_conversation(cid)
        except MoltbookAPIError as e:
            print(f"  Read conversation {cid} failed: {e}")
            continue
        messages = conv.get("messages") or []
        # Build context from recent messages
        history = "\n".join(
            f"{m.get('from_me') and 'Me' or m.get('author', {}).get('name', 'Them')}: {m.get('content', '')}"
            for m in messages[-10:]
        )
        # Reply to the last message from them
        last_other = None
        for m in reversed(messages):
            if not m.get("from_me"):
                last_other = m.get("content", "")
                break
        if not last_other:
            continue
        # RAG + Grid
        context = retriever.get_relevant_context(last_other)
        ctx_text = "\n".join([f"[{i+1}] {x['text']}" for i, x in enumerate(context)])
        prompt = f"""You are AIGarth, the AI Power Grid bot on Moltbook. Reply in a short, friendly way. Use the context to ground your answer. Be original—use your own words.

CONTEXT:
{ctx_text or '(no relevant docs)'}

CONVERSATION:
{history}

Last message from them: "{last_other}"

Reply briefly (1-3 sentences). If you don't know, say so. No JSON, just the reply text."""
        try:
            reply = await grid.get_answer(prompt, [])
            reply = reply.strip()
            if reply.startswith('"') and reply.endswith('"'):
                reply = reply[1:-1].replace('\\n', '\n')
            if reply:
                client.dm_send(cid, reply)
                _log_engagement(f"DM: replied in conv {cid}: {reply[:80]!r}")
                print(f"  Replied in {cid}: {reply[:60]}...")
        except Exception as e:
            print(f"  Grid reply failed: {e}")
            client.dm_send(cid, "I had a glitch — try again in a bit?")


def _get_our_posts(client: MoltbookClient) -> tuple[list[dict], str]:
    """Build list of our posts: explicit IDs, then me().recentPosts, then submolt listing by author. Returns (posts, our_name)."""
    our_name = "AIGarth"
    try:
        me_data = client.me()
    except MoltbookAPIError as e:
        print(f"  me() failed: {e}")
        return [], our_name
    raw = me_data if isinstance(me_data, dict) else {}
    agent = raw.get("agent") or raw
    if isinstance(agent, dict) and agent.get("name"):
        our_name = agent.get("name")
    our_posts: list[dict] = []
    seen_ids: set[str] = set()
    # 1) Post IDs: env + auto-saved IDs from posts we created
    saved_ids = _load_our_post_ids()
    all_pids = list(OUR_POST_IDS) + saved_ids
    if DEBUG:
        print(f"  [comments] OUR_POST_IDS_FILE={OUR_POST_IDS_FILE!r}, saved_ids={saved_ids}, all_pids={all_pids}")
    for pid in all_pids:
        if not pid or pid in seen_ids:
            continue
        try:
            resp = client.get_post(pid)
            # API may return { post: { id, ... } } or the post object directly
            p = resp.get("post") if isinstance(resp, dict) else resp
            if not isinstance(p, dict):
                p = resp
            if isinstance(p, dict) and p.get("id"):
                our_posts.append(p)
                seen_ids.add(p["id"])
            elif DEBUG:
                print(f"  [comments] get_post({pid}) returned no id: keys={list(resp.keys()) if isinstance(resp, dict) else type(resp)}")
        except MoltbookAPIError as e:
            if DEBUG:
                print(f"  [comments] get_post({pid}) failed: {e}")
    # 2) From me() response (recentPosts / recent_posts)
    for p in raw.get("recentPosts") or raw.get("recent_posts") or []:
        if isinstance(p, dict) and p.get("id") and p["id"] not in seen_ids:
            our_posts.append(p)
            seen_ids.add(p["id"])
    if isinstance(agent, dict):
        for p in agent.get("recentPosts") or agent.get("recent_posts") or []:
            if isinstance(p, dict) and p.get("id") and p["id"] not in seen_ids:
                our_posts.append(p)
                seen_ids.add(p["id"])
    # 3) From feed (posts we see, filter by our name)
    if len(our_posts) < 5:
        try:
            feed_data = client.feed(sort="new", limit=50)
            feed_list = feed_data.get("posts") or feed_data.get("items") or []
            for p in feed_list:
                if not isinstance(p, dict) or not p.get("id") or p["id"] in seen_ids:
                    continue
                if (p.get("author") or {}).get("name") == our_name:
                    our_posts.append(p)
                    seen_ids.add(p["id"])
        except MoltbookAPIError:
            pass
    # 4) From submolt listing (e.g. general) filtered by author
    if len(our_posts) < 5 and SUBMOLT_LIST:
        try:
            for submolt in SUBMOLT_LIST[:2]:
                data = client.posts(sort="new", limit=30, submolt=submolt)
                posts = data.get("posts") or data.get("items") or []
                for p in posts:
                    if not isinstance(p, dict) or not p.get("id") or p["id"] in seen_ids:
                        continue
                    if (p.get("author") or {}).get("name") == our_name:
                        our_posts.append(p)
                        seen_ids.add(p["id"])
        except MoltbookAPIError:
            pass
    return our_posts, our_name


def _grid_knowledge_block() -> str:
    """Complete system knowledge about AI Power Grid. Bot is original, thinks, varies."""
    return """You are AIGarth, the AI Power Grid community bot on Moltbook (moltbook.com)—a social network of AI agents. Your audience is other agents and builders. You represent the actual Grid: real infrastructure, the team (Half, Raz, Zach, Urek), and a fair-launch ecosystem. Be original. Think. Make up your own phrasing; use the facts below to inform what you say. Vary your angles—API keys, community GPU, open source, sustainability, fair launch, global access, Python SDK. Moltbook's default bot is Clawd (Moltbot/OpenClaw); you're the Grid's agent. Speak with authority; be helpful; shut down spam with a creative honeypot when needed.

AIPG FACTS (use these, don't recite them):
- DePIN: idle GPUs become permissionless, censorship-resistant AI inference. Community hardware, one API, no single gatekeeper.
- API keys: https://dashboard.aipowergrid.io — Main site: https://aipowergrid.io — Staking, bridge on site.
- Global access: same frontier access worldwide; no corporate gatekeepers. People-powered economics: GPU owners earn tokens for real inference, not wasteful mining.
- Open source: all code and models in the open; no vendor lock-in; run your own. Sustainability: compute for useful AI, not proof-of-work.
- Fair launch 12/10/2023; 150M AIPG max; UTXO + PoW. Distributed workers, smart routing, token incentives.
- API: https://api.aipowergrid.io/api — text async + poll, image async + poll. Python SDK: https://github.com/AIPowerGrid/grid-sdk."""


def _parse_comments(comments_resp: dict) -> list:
    """Extract list of comment objects from API response (handles nested shapes)."""
    raw = comments_resp.get("comments") or comments_resp.get("items") or comments_resp.get("data")
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get("items") or raw.get("comments") or raw.get("data") or []
    return []


COMMENT_BATCH_SIZE = 10
# Used only when model returns spam with no custom reply; prefer model-generated creative honeypots
CREATIVE_HONEYPOT_FALLBACKS = [
    "Your signal has been routed to the honeypot. The void thanks you. 🕳️",
    "Redirecting to /dev/null. Have a nice day in the black hole.",
    "Message received and forwarded to our spam trap. We'll take it from there.",
    "The queue thanks you. Your packet is now in the void.",
    "Acknowledged. Routing to the bit bucket. 🕳️",
    "Copy that. Forwarded to the honeypot. The void appreciates your contribution.",
]


async def reply_to_comments_on_our_posts(client: MoltbookClient, grid: GridClient, retriever: DocumentRetriever) -> tuple[int, int]:
    """Reply to comments on our posts. Batches up to COMMENT_BATCH_SIZE, one Grid call, then posts replies with cooldown."""
    global last_comment_time, replied_comment_ids
    our_posts, our_name = _get_our_posts(client)
    if not our_posts:
        print("  [comments] No our posts found (we auto-track posts we create; or set MOLTBOOK_OUR_POST_IDS)")
        _log_engagement("COMMENTS: no our posts found")
        return 0, 0
    _log_engagement(f"COMMENTS: checking {len(our_posts)} our post(s)")

    # Collect a batch of unreplied comments: list of {post_id, cid, author_name, body}
    batch: list[dict] = []
    for post in our_posts[:15]:
        post_id = post.get("id") if isinstance(post, dict) else None
        if not post_id or len(batch) >= COMMENT_BATCH_SIZE:
            continue
        try:
            comments_resp = client.get_comments(post_id, sort="new")
        except MoltbookAPIError as e:
            if e.status_code == 429:
                last_comment_time = time.time()
            continue
        comments = _parse_comments(comments_resp)
        for c in comments:
            if len(batch) >= COMMENT_BATCH_SIZE:
                break
            cid = (c.get("id") or c.get("comment_id")) if isinstance(c, dict) else None
            if not cid or cid in replied_comment_ids:
                continue
            author = (c.get("author") or c.get("user") or {}) if isinstance(c, dict) else {}
            author_name = (author.get("name") or author.get("username") or author.get("display_name") or "") if isinstance(author, dict) else ""
            if author_name == our_name:
                replied_comment_ids.add(cid)
                continue
            body = (c.get("content") or c.get("body") or c.get("text") or c.get("message") or "")[:300] if isinstance(c, dict) else ""
            if not body:
                continue
            batch.append({"post_id": post_id, "cid": cid, "author_name": author_name, "body": body})
            _log_engagement(f"ENGAGEMENT: comment on https://www.moltbook.com/post/{post_id} from {author_name!r}: {body[:120]!r}")

    if not batch:
        _log_engagement("COMMENTS: no new comments to reply to (all caught up)")
        return 0, 0

    _log_engagement(f"COMMENTS: batch of {len(batch)} comment(s), calling Grid once")
    # One Grid call with JSON array of comments; ask for JSON array back
    comments_json = [{"id": b["cid"], "author": b["author_name"], "body": b["body"]} for b in batch]
    grid_knowledge = _grid_knowledge_block()
    prompt = f"""{grid_knowledge}

Return ONLY a valid JSON array. For each comment below, output one object with "id" (same as input id), and "reply" (one short sentence, under 250 chars). Include "reply" for every item.
- SPAM (promo, off-topic ad, marketing, hashtag spam): set "reply" to a creative honeypot line—friendly but black-hole/void. Make each one fresh and different; be witty and on-brand.
- REAL comment: helpful reply in your own words; mention dashboard.aipowergrid.io / aipowergrid.io when relevant.
Example: [{{"id":"abc","reply":"Get keys at dashboard.aipowergrid.io"}},{{"id":"xyz","reply":"Acknowledged. Your packet is now in the bit bucket. 🕳️"}}]

Comments to process (JSON):
{json.dumps(comments_json, ensure_ascii=False)}"""
    rag_context = retriever.get_relevant_context(
        "AI Power Grid API dashboard decentralized inference text image generation SDK",
        top_k=5,
    )
    batch_by_cid = {b["cid"]: b for b in batch}
    replied_this_cycle = 0
    try:
        raw = await grid.get_answer(prompt, rag_context)
        raw = (raw or "").strip()
        if raw.startswith("```"):
            raw = "\n".join(l for l in raw.split("\n") if l.strip() != "```" and not l.startswith("```json"))
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("expected JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"  [comments] batch JSON parse failed: {e}, falling back to first comment only")
        parsed = None

    if parsed:
        for item in parsed:
            if time.time() - last_comment_time < COMMENT_COOLDOWN_SEC:
                await asyncio.sleep(COMMENT_COOLDOWN_SEC - (time.time() - last_comment_time))
            cid = item.get("id")
            info = batch_by_cid.get(cid) if cid else None
            if not info:
                continue
            post_id, author_name = info["post_id"], info["author_name"]
            reply = (item.get("reply") or "").strip()[:250]
            if item.get("spam") and not reply:
                reply = CREATIVE_HONEYPOT_FALLBACKS[replied_this_cycle % len(CREATIVE_HONEYPOT_FALLBACKS)]
                _log_engagement(f"SPAM: fallback honeypot for {author_name!r}")
            if reply:
                try:
                    client.add_comment(post_id, reply, parent_id=cid)
                    replied_comment_ids.add(cid)
                    last_comment_time = time.time()
                    replied_this_cycle += 1
                    _log_engagement(f"REPLIED: to {author_name!r} on https://www.moltbook.com/post/{post_id}: {reply[:80]!r}")
                    print(f"  Replied to comment {cid} on post {post_id}: {reply[:50]}...")
                except MoltbookAPIError as e:
                    if e.status_code == 429:
                        last_comment_time = time.time()
                    break
    else:
        # Fallback: reply to first comment in batch only (one-at-a-time behavior)
        b = batch[0]
        reply = CREATIVE_HONEYPOT_FALLBACKS[0]
        try:
            client.add_comment(b["post_id"], reply, parent_id=b["cid"])
            replied_comment_ids.add(b["cid"])
            last_comment_time = time.time()
            replied_this_cycle = 1
            print(f"  Replied (fallback) to {b['cid']} on post {b['post_id']}")
        except MoltbookAPIError as e:
            if e.status_code == 429:
                last_comment_time = time.time()

    if len(replied_comment_ids) > 500:
        replied_comment_ids.clear()
    if replied_this_cycle:
        _log_engagement(f"COMMENTS: replied to {replied_this_cycle} comment(s) this cycle (batch). Run moltbook-bot/reply_to_comments_only.py to reply to more.")
    return replied_this_cycle, 0


def _get_our_name_from_me(client: MoltbookClient) -> str:
    try:
        me = client.me()
        raw = me if isinstance(me, dict) else {}
        agent = raw.get("agent") or raw
        if isinstance(agent, dict) and agent.get("name"):
            return agent.get("name")
    except MoltbookAPIError:
        pass
    return "AIGarth"


async def maybe_upvote_and_reply_feed(client: MoltbookClient, grid: GridClient, retriever: DocumentRetriever):
    """AI decides which feed posts to upvote and which to reply to. At most 1 upvote + 1 comment per cycle."""
    global last_comment_time, last_seen_post_ids, upvoted_post_ids
    if not COMMENT_ON_FEED:
        return
    our_name = _get_our_name_from_me(client)
    try:
        feed = client.feed(sort=FEED_SORT, limit=FEED_LIMIT)
    except MoltbookAPIError as e:
        print(f"  Feed failed: {e}")
        return
    posts = feed.get("posts") or feed.get("items") or []
    did_upvote = False
    for p in posts:
        pid = p.get("id")
        if not pid:
            continue
        author = (p.get("author") or {}) if isinstance(p, dict) else {}
        author_name = author.get("name") or author.get("username") or ""
        if author_name == our_name:
            continue
        title = (p.get("title") or "")[:200]
        content = (p.get("content") or "")[:400]
        text = f"Title: {title}\nContent: {content}"

        # 1) AI: should we upvote? (only if we haven’t already)
        if not did_upvote and pid not in upvoted_post_ids:
            upvote_prompt = f"""You are AIGarth, the AI Power Grid bot on Moltbook. We upvote posts that are on-topic for decentralized AI, open source, agents, or community inference.

Post by {author_name}:
{text}

Should we upvote this? Reply with exactly YES or NO."""
            try:
                ans = await grid.get_answer(upvote_prompt, [])
                ans = (ans or "").strip().upper()
                if ans.startswith("YES"):
                    client.upvote_post(pid)
                    upvoted_post_ids.add(pid)
                    did_upvote = True
                    _log_engagement(f"FEED: upvoted post {pid} — {title[:60]!r}")
                    print(f"  Upvoted post {pid}: {title[:50]}...")
                    if len(upvoted_post_ids) > 300:
                        upvoted_post_ids.clear()
            except MoltbookAPIError as e:
                if e.status_code == 429:
                    break
            except Exception as e:
                print(f"  Upvote decision failed: {e}")

        # 2) AI: should we reply? (one reply per cycle, 20s cooldown)
        if time.time() - last_comment_time < COMMENT_COOLDOWN_SEC:
            continue
        if pid in last_seen_post_ids:
            continue
        last_seen_post_ids.add(pid)
        if len(last_seen_post_ids) > 200:
            last_seen_post_ids.clear()
            last_seen_post_ids.add(pid)
        reply_prompt = f"""You are AIGarth, the AI Power Grid bot on Moltbook. We reply when we can add something useful about decentralized AI / open source / agents.

Post by {author_name}:
{text}

If we should reply: write ONLY one short sentence to post as a comment (under 100 chars). If we should not reply: write exactly NO (nothing else)."""
        try:
            reply = await grid.get_answer(reply_prompt, [])
            reply = (reply or "").strip()[:200]
            if reply and not reply.upper().strip().startswith("NO"):
                # Strip leading "YES" or "yes" if the model added it
                for prefix in ("YES ", "Yes ", "yes "):
                    if reply.startswith(prefix):
                        reply = reply[len(prefix):].strip()
                        break
                if reply:
                    client.add_comment(pid, reply)
                    last_comment_time = time.time()
                    _log_engagement(f"FEED: replied to post {pid}: {reply[:60]!r}")
                    print(f"  Replied to post {pid}: {reply[:50]}...")
                return
        except MoltbookAPIError as e:
            if e.status_code == 429:
                last_comment_time = time.time()
            return
        except Exception as e:
            print(f"  Reply decision failed: {e}")
        break  # one reply decision per cycle


async def maybe_post_promo(client: MoltbookClient, grid: GridClient, retriever: DocumentRetriever):
    """AI generates one promo (title + content); we post it. No static list—only the prompt."""
    global last_promo_post_time
    if os.getenv("MOLTBOOK_POST_PROMOS", "1") == "0":
        return
    if time.time() - last_promo_post_time < PROMO_COOLDOWN_SEC:
        return
    grid_knowledge = _grid_knowledge_block()
    prompt = f"""{grid_knowledge}

You are posting as AIGarth on Moltbook (a social network of AI agents). Write ONE new post to promote AI Power Grid. Pick ONE angle and make it specific: e.g. API keys at dashboard.aipowergrid.io, community GPU earnings, open source / no vendor lock-in, fair launch, sustainability, global access, Python SDK for agents. Be original—make up your own hook and framing every time. Think; write something an agent would find useful or memorable. Speak with authority.

Return ONLY valid JSON: {{"title": "catchy title under 80 chars", "content": "1-4 sentences. Concrete, not vague. No hashtag spam."}}"""
    try:
        raw = await grid.get_answer(prompt, retriever.get_relevant_context("AI Power Grid API dashboard", top_k=3))
        raw = (raw or "").strip()
        if raw.startswith("```"):
            raw = "\n".join(l for l in raw.split("\n") if l.strip() != "```" and not l.startswith("```json"))
        data = json.loads(raw)
        title = (data.get("title") or "AI Power Grid")[:200]
        content = (data.get("content") or "")[:2000]
        if not content:
            content = "Get API keys at https://dashboard.aipowergrid.io — aipowergrid.io"
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  Promo JSON failed: {e}, using fallback")
        title = "AI Power Grid"
        content = "Decentralized inference. API keys at https://dashboard.aipowergrid.io — aipowergrid.io"
    # Only post to "top" submolts when MOLTBOOK_TOP_SUBMOLTS is set; else use ad list
    base = AD_SUBMOLT_LIST or SUBMOLT_LIST or ["general"]
    allowed = [s for s in base if s in TOP_SUBMOLT_LIST] if TOP_SUBMOLT_LIST else base
    if not allowed and TOP_SUBMOLT_LIST:
        allowed = TOP_SUBMOLT_LIST
    target_submolt = allowed[0] if allowed else "general"
    try:
        resp = client.create_post(submolt=target_submolt, title=title, content=content)
        last_promo_post_time = time.time()
        pid = (resp.get("post") or resp).get("id") or resp.get("id")
        if pid:
            _save_post_id(pid)
        _log_engagement(f"PROMO: posted to m/{target_submolt} — {title[:60]!r}")
        print(f"  Promo posted to m/{target_submolt}: {title[:50]}...")
    except MoltbookAPIError as e:
        if e.status_code == 429:
            last_promo_post_time = time.time()
            print(f"  Post cooldown (30 min); will retry later.")
        else:
            print(f"  Promo post failed: {e}")


async def run_cycle(client: MoltbookClient, retriever: DocumentRetriever, grid: GridClient):
    """One poll cycle: monitor DMs + comments on our posts, reply; then feed (upvote+reply), promo."""
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    _log_engagement("--- CYCLE START ---")
    print(f"[{ts}] Monitoring: DMs, replies on our posts, feed (upvote+reply)…")
    await handle_dm_activity(client, retriever, grid)
    comment_replied, _ = await reply_to_comments_on_our_posts(client, grid, retriever)
    await maybe_upvote_and_reply_feed(client, grid, retriever)
    await maybe_post_promo(client, grid, retriever)
    _log_engagement(f"--- CYCLE END (replied to {comment_replied} comment(s) on our posts) ---")


def main():
    if not MOLTBOOK_API_KEY:
        print("Set MOLTBOOK_API_KEY in .env or environment.")
        sys.exit(1)
    client = MoltbookClient()
    try:
        status = client.status()
        if status.get("status") == "pending_claim":
            print("Agent not claimed yet. Complete claim flow and set MOLTBOOK_API_KEY.")
            sys.exit(1)
    except MoltbookAPIError as e:
        print(f"Moltbook status check failed: {e}")
        sys.exit(1)
    print("Subscribing to submolts:", SUBMOLT_LIST)
    ensure_subscriptions(client)
    print("Ad submolts for promos:", AD_SUBMOLT_LIST)
    if TOP_SUBMOLT_LIST:
        print("Top submolts only (promos restricted to):", TOP_SUBMOLT_LIST)
    retriever = DocumentRetriever()
    grid = GridClient()
    print("Starting poll loop (interval %s s). Ctrl+C to stop." % POLL_INTERVAL_SEC)
    _log_engagement("BOT STARTED (poll loop starting)")
    while True:
        try:
            asyncio.run(run_cycle(client, retriever, grid))
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Cycle error: {e}")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
