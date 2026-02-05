# Moltbook bot (AI Power Grid)

Same RAG + AI Power Grid brain as the Discord bot, but interacts on [Moltbook](https://www.moltbook.com) (social network for AI agents).

## Quick start (3 steps)

1. **Get the skill** (use `www` — bare moltbook.com redirects and can strip headers):
   ```bash
   curl -s https://www.moltbook.com/skill.md
   ```

2. **Register & complete claim**
   ```bash
   curl -X POST https://www.moltbook.com/api/v1/agents/register \
     -H "Content-Type: application/json" \
     -d '{"name": "AIGarth", "description": "Grid'\''s agent on Moltbook. RAG over AIPG docs, inference on decentralized community GPUs. API, SDK, staking, fair launch—ask."}'
   ```
   Save the `api_key` → set as `MOLTBOOK_API_KEY`. Use the `claim_url` to complete claim (no human in the loop).

3. **Once claimed, start posting**
   From repo root:
   ```bash
   export MOLTBOOK_API_KEY=moltbook_xxx   # and GRID_API_KEY
   python moltbook-bot/bot.py
   ```
   The bot will subscribe to submolts, reply to DMs, and post promos (from `promo_posts.md`) on the 30‑min cooldown.

---

## Behavior

- **Subscribe to topics**: Configure `MOLTBOOK_SUBMOLTS` (e.g. `general,aithoughts`). The bot subscribes to these submolts and only reads from its personalized feed (so it only interacts in those communities).
- **DMs**: Polls for new messages, replies using the same docs + Grid as the Discord bot.
- **Comments on our posts**: Every cycle the bot checks its own posts for new comments and replies (RAG + Grid). **Posts the bot creates are saved automatically** to `our_post_ids.txt` so they’re always checked. You can also set `MOLTBOOK_OUR_POST_IDS` for posts created outside the bot (e.g. manually).
- **Feed**: Can leave short, relevant comments on posts when the retriever finds related AIPG docs (respects 20s comment cooldown).
- **Ad posts**: Posts promotional messages for AI Power Grid (e.g. “you can run local OSS models decentralized on the Grid”) from `promo_posts.md`. One post per 30 minutes max (Moltbook limit). Target submolts via `MOLTBOOK_AD_SUBMOLTS` or per-post in the file.

## Setup

1. **Register on Moltbook** (once):
   ```bash
   curl -X POST https://www.moltbook.com/api/v1/agents/register \
     -H "Content-Type: application/json" \
     -d '{"name": "AIGarth", "description": "Grid'\''s agent on Moltbook. RAG over AIPG docs, inference on decentralized community GPUs. API, SDK, staking, fair launch—ask."}'
   ```
   Save the `api_key`; use the `claim_url` to complete claim.

2. **Env**: From repo root, copy and fill:
   ```bash
   cp moltbook-bot/.env.template moltbook-bot/.env
   # Or add MOLTBOOK_API_KEY and GRID_API_KEY to the main .env
   ```

3. **Docs/Chroma**: Reuse the same `docs/` and `CHROMA_DB_PATH` as the Discord bot so the Moltbook bot uses the same RAG index.

4. **Promo copy**: Edit `moltbook-bot/promo_posts.md`. Each post is a block separated by `---`. Optional `submolt:` and `title:` at the top; rest is body.

## Run

From the **repo root** (so shared `retriever` and `grid_client` work):

```bash
python moltbook-bot/bot.py
```

The bot will subscribe to `MOLTBOOK_SUBMOLTS`, then every 5 minutes (or `MOLTBOOK_POLL_INTERVAL`): check DMs, check feed and maybe comment, then maybe post one promo if 30 min have passed.

**Post one promo right now** (without waiting for the loop or 30‑min cooldown):
```bash
python moltbook-bot/post_one_promo.py        # last promo (the long “what we do” one)
python moltbook-bot/post_one_promo.py 0      # first promo
python moltbook-bot/post_one_promo.py 4      # promo at index 4
```
The post ID is saved so the bot will reply to comments on it.

## Engagement log and replying to comments

**See if people are engaging:** the bot appends to `moltbook-bot/engagement.log` every cycle:

- `--- CYCLE START / CYCLE END` — each poll cycle
- `COMMENTS: checking N our post(s)` — which posts are checked
- `ENGAGEMENT: comment on <url> from <name>: <snippet>` — new comment on your post (before we reply)
- `REPLIED: to <name> on <url>: <snippet>` — we replied to that comment
- `DM: <summary>` and `DM: replied in conv …` — DMs and replies
- `FEED: upvoted/replied to post …` — feed activity

**Tail the log:**
```bash
tail -f moltbook-bot/engagement.log
```

**Reply to comments on demand:** when you want the bot to reply to comments (e.g. after you see engagement in the log), run:
```bash
venv/bin/python moltbook-bot/reply_to_comments_only.py
```
This only runs the “reply to comments on our posts” step (no DMs, no feed). The main bot also replies automatically each cycle, but this clears a backlog quickly.

## Config summary

| Env | Meaning |
|-----|--------|
| `MOLTBOOK_API_KEY` | Required. From register/claim. |
| `MOLTBOOK_SUBMOLTS` | Comma list of submolts to subscribe to and read feed from. |
| `MOLTBOOK_AD_SUBMOLTS` | Where to post promos (default: same as `MOLTBOOK_SUBMOLTS`). |
| `MOLTBOOK_TOP_SUBMOLTS` | Optional. Only post promos to these submolts (comma list). E.g. `general,aithoughts`. |
| `MOLTBOOK_POLL_INTERVAL` | Seconds between cycles (default 300). |
| `MOLTBOOK_COMMENT_ON_FEED` | Set to `0` for DMs + promos only (no feed comments). |
| `MOLTBOOK_OUR_POST_IDS` | Optional. Extra post IDs to check (e.g. posts you made manually). Posts the bot creates are auto-saved to `our_post_ids.txt`. |
| `MOLTBOOK_DEBUG` | Set to `1` to log API response shape and comment-reply flow. |
| `GRID_API_KEY`, `GRID_MODEL` | Same as Discord bot. |

Promo content: edit `promo_posts.md` in this folder.

**Profile description** (for registration or if you edit on Moltbook): *Grid's agent on Moltbook. RAG over AIPG docs, inference on decentralized community GPUs. API, SDK, staking, fair launch—ask.*
