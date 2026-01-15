import os
import re
import json
import asyncio
import discord
import datetime
import requests
from bs4 import BeautifulSoup
from io import BytesIO
from dotenv import load_dotenv
from retriever import DocumentRetriever
from grid_client import GridClient
from coingecko_mcp import get_crypto_context
from conversation_db import (
    init_db, add_message, format_channel_history,
    format_mood, format_memories, format_recent_happenings,
    get_channel_status, set_channel_status, format_channel_statuses
)

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Parse channel lists
def parse_channel_ids(env_var: str) -> list:
    """Parse comma-separated channel IDs from env var."""
    ids = []
    for channel_id in os.getenv(env_var, '').split(','):
        if channel_id.strip():
            try:
                ids.append(int(channel_id.strip()))
            except ValueError:
                print(f"Warning: Invalid channel ID '{channel_id}' in {env_var}, skipping")
    return ids

# Active channels: bot responds + stores in vector DB
BOT_CHANNELS = parse_channel_ids('BOT_CHANNELS')
# Read-only channels: bot stores in vector DB but doesn't respond  
BOT_READONLY_CHANNELS = parse_channel_ids('BOT_READONLY_CHANNELS')
# Combined: all channels bot should store messages from
ALL_BOT_CHANNELS = set(BOT_CHANNELS + BOT_READONLY_CHANNELS)

BOT_NAME = os.getenv('BOT_NAME', 'ask-ai')  # Configurable bot name
admin_id_str = os.getenv('ADMIN_USER_ID', '0')
print(f"Admin ID from env: '{admin_id_str}'")
ADMIN_USER_ID = 0
try:
    ADMIN_USER_ID = int(admin_id_str)
except ValueError:
    print(f"Warning: Invalid ADMIN_USER_ID '{admin_id_str}', using 0")

# Initialize the bot
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True  # Make sure we have message intents
intents.reactions = True  # Need reactions for voting
intents.members = True  # Need members intent for banning
client = discord.Client(intents=intents)

# Initialize document retriever and Grid client
retriever = DocumentRetriever()
grid_client = GridClient()

# Scam detection and voting
BAN_VOTE_THRESHOLD = 3  # Number of upvotes needed to ban
DISMISS_VOTE_THRESHOLD = 3  # Number of downvotes needed to dismiss
pending_ban_votes = {}  # {message_id: {'target_user_id': int, 'reason': str, 'upvotes': set, 'downvotes': set}}

# Command prefixes
COMMANDS = {
    'help': '!help',
    'upload': '!upload',
    'list': '!list',
    'delete': '!delete'
}

@client.event
async def on_ready():
    """Event called when the bot is ready."""
    # Initialize database
    init_db()
    
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print(f'Bot name: {BOT_NAME}')
    print(f'Active channels (respond + store): {BOT_CHANNELS}')
    print(f'Read-only channels (store only): {BOT_READONLY_CHANNELS}')
    print(f'Admin user ID: {ADMIN_USER_ID}')
    print('------')

def extract_urls_from_message(message_content: str) -> list[str]:
    """Extract all URLs from a message."""
    url_patterns = [
        r'https?://[^\s\)\]>]+',  # Match URLs, stop at whitespace/paren/bracket
        r'www\.[^\s\)\]>]+',
        r'discord\.gg/[^\s\)\]>]+',  # Discord invites without https
        r'discord\.com/invite/[^\s\)\]>]+',  # Discord invites alternate format
    ]
    
    urls = []
    for pattern in url_patterns:
        matches = re.findall(pattern, message_content, re.IGNORECASE)
        urls.extend(matches)
    
    # Deduplicate while preserving order
    seen = set()
    unique_urls = []
    for url in urls:
        if url.lower() not in seen:
            seen.add(url.lower())
            unique_urls.append(url)
    
    return unique_urls

def extract_opengraph(url: str, timeout: int = 5) -> dict:
    """Extract OpenGraph metadata from a URL for AI context."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)'
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return {}
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        og_data = {}
        
        for tag in soup.find_all('meta'):
            prop = tag.get('property', '') or tag.get('name', '')
            content = tag.get('content', '')
            if prop in ['og:title', 'og:description', 'og:site_name', 'twitter:title', 'twitter:description']:
                og_data[prop] = content[:500]  # Limit length
        
        return og_data
    except Exception as e:
        print(f"OpenGraph extraction failed for {url}: {e}")
        return {}

def format_link_context(urls: list[str]) -> str:
    """Extract and format OpenGraph data for all URLs in a message."""
    if not urls:
        return ""
    
    link_info = []
    for url in urls[:3]:  # Limit to 3 URLs to avoid slowdown
        og = extract_opengraph(url)
        if og:
            title = og.get('og:title') or og.get('twitter:title', '')
            desc = og.get('og:description') or og.get('twitter:description', '')
            site = og.get('og:site_name', '')
            
            info = f"Link: {url}"
            if site:
                info += f"\n  Site: {site}"
            if title:
                info += f"\n  Title: {title}"
            if desc:
                info += f"\n  Description: {desc[:200]}..."
            link_info.append(info)
        else:
            link_info.append(f"Link: {url} (no preview available)")
    
    if link_info:
        return "\n\n=== LINK PREVIEWS ===\n" + "\n\n".join(link_info)
    return ""

async def analyze_message_for_scam(message_content: str, urls: list[str]) -> tuple[bool, str]:
    """Use AI Power Grid to analyze if a message with links is a scam.
    AI has full context about trusted domains and scam patterns."""
    
    urls_text = "\n".join([f"- {url}" for url in urls])
    
    analysis_prompt = f"""You are a security bot for the AI Power Grid Discord server. Analyze this message and decide if it's a scam.

MESSAGE: "{message_content}"

LINKS IN MESSAGE:
{urls_text}

TRUSTED DOMAINS (always safe, never flag these):
- aipowergrid.io, aipg (anything with aipg/aipowergrid)
- Block explorers: etherscan.io, polygonscan.com, basescan.org, bscscan.com, arbiscan.io, snowtrace.io, ftmscan.com
- Price trackers: coingecko.com, coinmarketcap.com, coinpaprika.com, livecoinwatch.com
- DEXes: uniswap.org, pancakeswap.finance, aerodrome.finance, curve.fi, balancer.fi, sushi.com, 1inch.io
- L2/Superchain: base.org, optimism.io, arbitrum.io, zksync.io
- Crypto tools: dextools.io, dexscreener.com, defined.fi
- Social: github.com, twitter.com, x.com, medium.com, reddit.com, youtube.com

ALWAYS FLAG AS SCAM:
- Discord invite links (discord.gg, discord.com/invite) - we don't allow server invites
- Fake support/help desk links (zendesk, freshdesk, "support ticket" sites not from trusted domains)
- Wallet verification or migration scams
- Fake airdrop claim sites
- Phishing sites impersonating legitimate services

SAFE - DO NOT FLAG:
- Links to any trusted domain listed above
- Normal crypto discussion with legitimate links
- News articles, documentation, tutorials

Return ONLY a JSON object:
{{"is_scam": true/false, "reason": "brief explanation"}}

Be specific in reason (e.g., "Discord invite link", "fake support site", "trusted DEX link - safe").
Only return the JSON, nothing else."""
    
    try:
        result = await grid_client.get_answer(analysis_prompt, [])
        print(f"🤖 AI Scam Analysis: '{result}'")
        
        # Parse JSON response
        result_clean = result.strip()
        if result_clean.startswith('```'):
            result_clean = result_clean.split('```')[1]
            if result_clean.startswith('json'):
                result_clean = result_clean[4:]
        result_clean = result_clean.strip()
        
        analysis = json.loads(result_clean)
        return analysis.get('is_scam', False), analysis.get('reason', 'analyzed by AI')
        
    except json.JSONDecodeError as e:
        print(f"Failed to parse AI response: {e}, raw: '{result}'")
        # Only flag if it looks suspicious - don't flag on parse errors for trusted domains
        for trusted in ['aipg', 'etherscan', 'coingecko', 'uniswap', 'github', 'twitter']:
            if any(trusted in url.lower() for url in urls):
                return False, "parse error but trusted domain detected"
        return True, "AI analysis failed - flagged for review"
    except Exception as e:
        print(f"Error in AI scam analysis: {e}")
        return True, "AI analysis error - flagged for review"

async def handle_scam_detection(message):
    """Check message for scams using AI. Creates a ban vote if scam detected."""
    # Don't check admins
    if message.author.id == ADMIN_USER_ID:
        return False
    
    # Extract URLs - no URLs means no scam check needed
    urls = extract_urls_from_message(message.content)
    
    # Also check for Discord invite patterns that might be obfuscated
    discord_invite_patterns = ['discord.gg', 'discord.com/invite', 'discordapp.com/invite']
    has_discord_invite = any(pattern in message.content.lower() for pattern in discord_invite_patterns)
    
    if not urls and not has_discord_invite:
        return False
    
    if has_discord_invite and not urls:
        # Found invite pattern but no URL extracted - flag it anyway
        urls = ["[obfuscated discord invite detected]"]
    
    log_msg = f"🚨 SCAM CHECK: {len(urls)} URL(s) from {message.author.display_name}: {urls}"
    print(log_msg, flush=True)
    with open('bot.log', 'a') as f:
        f.write(log_msg + '\n')
    
    # Let AI decide
    is_scam, reason = await analyze_message_for_scam(message.content, urls)
    
    if not is_scam:
        print(f"✅ AI says safe: {reason}")
        return False
    
    # Redact URLs from the original message for evidence
    redacted_content = message.content
    for url in urls:
        if url != "[obfuscated discord invite detected]":
            redacted_content = redacted_content.replace(url, "[LINK REDACTED]")
    # Also redact any remaining discord invite patterns
    redacted_content = re.sub(r'discord\.gg/\S+', '[LINK REDACTED]', redacted_content, flags=re.IGNORECASE)
    redacted_content = re.sub(r'discord\.com/invite/\S+', '[LINK REDACTED]', redacted_content, flags=re.IGNORECASE)
    # Truncate if too long
    if len(redacted_content) > 500:
        redacted_content = redacted_content[:500] + "..."
    
    # Create vote message with evidence
    vote_message_text = (
        f"🚨 **Ban {message.author.mention} ({message.author.display_name})?**\n"
        f"**Reason:** {reason}\n\n"
        f"📝 **Their message (saved before deletion):**\n"
        f"```{redacted_content}```\n"
        f"React ✅ to ban, ❌ to dismiss"
    )
    
    try:
        vote_message = await message.channel.send(vote_message_text)
        
        # Bot automatically adds its own ban vote (1 vote from bot, chat needs 2 more)
        await vote_message.add_reaction('✅')
        await vote_message.add_reaction('❌')
        
        # Store vote info with bot's vote already counted
        pending_ban_votes[vote_message.id] = {
            'target_user_id': message.author.id,
            'target_user_name': message.author.display_name,
            'reason': reason,
            'original_message_id': message.id,
            'channel_id': message.channel.id,
            'upvotes': {client.user.id},  # Bot's vote counts as 1
            'downvotes': set()
        }
        
        print(f"🚨 Scam detected! Created ban vote for {message.author.display_name}: {reason} (Bot voted ✅, chat needs 2 more)")
        return True
        
    except Exception as e:
        print(f"Error creating ban vote: {e}")
        return False

def should_respond(message) -> bool:
    """Basic sanity checks only. AI sees conversation history and decides."""
    content = message.content
    
    # Don't respond to self
    if message.author.id == client.user.id:
        return False
    
    # Skip command messages (handled elsewhere)
    if content.startswith('!'):
        return False
    
    # Skip empty messages
    if not content.strip():
        return False
    
    # Let the AI see everything else and decide
    return True

def format_file_size(size_bytes):
    """Format file size in a human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"

def format_timestamp(timestamp):
    """Format a Unix timestamp to a human-readable date."""
    dt = datetime.datetime.fromtimestamp(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

async def handle_help_command(message):
    """Handle the !help command."""
    help_embed = discord.Embed(
        title="aigarth Help",
        description="I'm your AI-powered chat buddy for the AI Power Grid community! I can answer questions using stored documentation and live market data.",
        color=discord.Color.green()
    )
    
    help_embed.add_field(
        name="How to use",
        value="Mention me with your question or ask naturally in the listening channel! I'll respond when I think I can help.",
        inline=False
    )
    
    help_embed.add_field(
        name="Example",
        value="@BotName What security features does AI Power Grid offer?",
        inline=False
    )
    
    help_embed.add_field(
        name="Conversation",
        value="I remember recent conversation context to provide better answers.",
        inline=False
    )
    
    # Add document management commands
    if message.author.id == ADMIN_USER_ID:
        help_embed.add_field(
            name="Document Management (Admin Only)",
            value=f"`{COMMANDS['upload']}` - Upload a document (attach a file)\n"
                  f"`{COMMANDS['list']}` - List all documents\n"
                  f"`{COMMANDS['delete']} [filename]` - Delete a document",
            inline=False
        )
    
    await message.channel.send(embed=help_embed)

async def handle_upload_command(message):
    """Handle the !upload command."""
    # Check if user is authorized
    if message.author.id != ADMIN_USER_ID:
        await message.channel.send("You don't have permission to upload documents.")
        return
    
    # Check if there are attachments
    if not message.attachments:
        await message.channel.send("Please attach a file to upload.")
        return
    
    # Process each attachment
    results = []
    for attachment in message.attachments:
        filename = attachment.filename
        file_ext = filename.split('.')[-1].lower() if '.' in filename else ''
        
        # Check if file type is supported
        if file_ext not in ['txt', 'md', 'mdx']:
            results.append(f"❌ {filename}: Unsupported file type. Only .txt, .md, and .mdx files are supported.")
            continue
        
        try:
            # Download the file content
            content = await attachment.read()
            content_str = content.decode('utf-8')
            
            # Ingest the content
            result = retriever.ingest_content(content_str, filename)
            results.append(f"✅ {result}")
        except Exception as e:
            results.append(f"❌ {filename}: Error - {str(e)}")
    
    # Send results
    result_message = "\n".join(results)
    await message.channel.send(f"Document upload results:\n{result_message}")

async def handle_list_command(message):
    """Handle the !list command."""
    # Check if user is authorized
    if message.author.id != ADMIN_USER_ID:
        await message.channel.send("You don't have permission to list documents.")
        return
    
    documents = retriever.list_documents()
    
    if not documents:
        await message.channel.send("No documents found.")
        return
    
    # Create an embed to display the documents
    list_embed = discord.Embed(
        title="Available Documents",
        description=f"Total documents: {len(documents)}",
        color=discord.Color.blue()
    )
    
    # Add each document to the embed
    for i, doc in enumerate(documents[:25]):  # Limit to 25 to avoid Discord embed limits
        file_size = format_file_size(doc['size'])
        modified_time = format_timestamp(doc['last_modified'])
        list_embed.add_field(
            name=f"{i+1}. {doc['filename']}",
            value=f"Size: {file_size}\nLast modified: {modified_time}",
            inline=True
        )
    
    # If there are more documents than we displayed
    if len(documents) > 25:
        list_embed.set_footer(text=f"Showing 25 of {len(documents)} documents. Use {COMMANDS['list']} to view more.")
    
    await message.channel.send(embed=list_embed)

async def handle_delete_command(message):
    """Handle the !delete command."""
    # Check if user is authorized
    if message.author.id != ADMIN_USER_ID:
        await message.channel.send("You don't have permission to delete documents.")
        return
    
    # Extract the filename from the command
    command_parts = message.content.split(maxsplit=1)
    if len(command_parts) < 2:
        await message.channel.send(f"Please specify a document to delete. Usage: `{COMMANDS['delete']} [filename]`")
        return
    
    filename = command_parts[1].strip()
    
    try:
        result = retriever.delete_document(filename)
        await message.channel.send(f"✅ {result}")
    except FileNotFoundError:
        await message.channel.send(f"❌ Document not found: {filename}")
    except Exception as e:
        await message.channel.send(f"❌ Error deleting document: {str(e)}")

async def classify_and_respond(message):
    """Main response handler. Stores messages and optionally responds."""
    content = message.content.strip()
    author_name = message.author.display_name
    
    # Always save to history (both active and readonly channels)
    add_message(message.channel.id, author_name, content, author_id=message.author.id, is_bot=False)
    
    # Read-only channels: store only, don't respond
    if message.channel.id in BOT_READONLY_CHANNELS:
        return False
    
    # Single filter check
    if not should_respond(message):
        return False
    
    print(f"\n🔍 Processing: '{content[:80]}...' from {author_name}")
    
    try:
        # Get conversation history for context
        conversation_history = format_channel_history(message.channel.id, max_messages=10)
        
        # Retrieve relevant documents for the response
        context = retriever.get_relevant_context(content)
        
        # Get crypto market data if relevant
        crypto_context = await get_crypto_context(content)
        
        # Extract link previews if message contains URLs
        urls = extract_urls_from_message(content)
        link_context = format_link_context(urls) if urls else ""
        
        # Get mood, memories, and recent happenings
        mood_info = format_mood()
        memories_info = format_memories()
        happenings_info = format_recent_happenings()
        
        # Get chattiness level from memory
        from conversation_db import get_memory
        chattiness_raw = get_memory('chattiness_level')
        chattiness_level = int(chattiness_raw) if chattiness_raw and chattiness_raw.isdigit() else 5  # Default to 5 (balanced)
        
        # Generate chattiness-specific guidance
        chattiness_guidance = ""
        if chattiness_level <= 3:
            chattiness_guidance = "\n- Be selective - only respond to highly relevant messages or clear opportunities to help"
        elif chattiness_level >= 7:
            chattiness_guidance = "\n- Be more proactive - feel free to chime in on relevant discussions even if not directly asked\n- Share insights, add context, or contribute to ongoing topics when you have something valuable to add"
        # 4-6: use default behavior (no extra guidance)
        
        # Get channel statuses (cross-channel awareness)
        channel_statuses = format_channel_statuses(message.channel.id)
        current_channel_status = get_channel_status(message.channel.id) or "No status yet - this is your first time here."
        
        # Get channel information
        channel_name = message.channel.name if hasattr(message.channel, 'name') else f"Channel {message.channel.id}"
        channel_topic = ""
        if hasattr(message.channel, 'topic') and message.channel.topic:
            channel_topic = message.channel.topic
        elif hasattr(message.channel, 'description') and message.channel.description:
            channel_topic = message.channel.description
        
        channel_info = f"Channel: #{channel_name}"
        if channel_topic:
            channel_info += f"\nChannel description: {channel_topic}"
        
        # Single API call with JSON response
        current_time = datetime.datetime.now()
        timestamp = current_time.strftime("%B %d, %Y at %I:%M %p")
        
        single_prompt = f"""You are {BOT_NAME}, the AI assistant for the AI Power Grid community.

WHO YOU ARE: You are powered by distributed LLM workers on the AI Power Grid network. Your responses are generated by decentralized GPU workers who earn AIPG tokens for providing inference. You're proof that the Grid works - a real AI running on community-powered infrastructure, not centralized cloud servers.

Current time: {timestamp}

=== CURRENT CHANNEL ===
{channel_info}
Your status note for this channel: {current_channel_status}

=== YOUR STATE ===
{mood_info}
{memories_info}

=== OTHER CHANNELS (background awareness) ===
{channel_statuses}

=== THIS CHANNEL'S CONVERSATION (your focus) ===
{conversation_history}

Latest message from {author_name}: "{content}"

NOTE: Your Discord ID is {client.user.id}. If you see "<@{client.user.id}>" in the message above, that means YOU are being @mentioned - someone is talking directly to you! ALWAYS respond when mentioned!

=== RELEVANT DOCUMENTATION ===
{chr(10).join([f"[{i+1}] {item['text']}" for i, item in enumerate(context)])}
{crypto_context}
{link_context}

=== BEHAVIOR ===
IMPORTANT: The "Latest message" above is what you're responding to. Focus on THAT message, not old conversation history.

Chattiness Level: {chattiness_level}/10

Your name is "{BOT_NAME}". ALWAYS respond when:
- You are @mentioned - someone is talking TO YOU, always reply!
- Someone says your name "{BOT_NAME}" anywhere in the message - they want your attention, respond!
- Someone asks you a direct question{chattiness_guidance}

Stay quiet ONLY when:
- People are clearly chatting with each other and NOT mentioning you at all
- Random messages that have nothing to do with you

Be natural and conversational. If someone just says "hey {BOT_NAME}" or "{BOT_NAME} are you there" - just say hi! Keep it simple.

For quick acknowledgments, use emoji reactions (👍 ✅ 🎉 🔥 etc.) instead of long messages.

=== RESPONSE FORMAT ===
Return JSON with these fields:
- "respond": true/false (required)
- "message": your response text (optional)
- "react": emoji to react with (optional)
- "channel_status": brief summary of what's happening in this channel now (optional but encouraged - helps you remember next time)

Examples:
{{"respond": true, "message": "The bridge is live on Base!", "channel_status": "Discussing Base bridge. User asking about migration."}}
{{"respond": true, "react": "👍", "channel_status": "General chat, nothing urgent."}}
{{"respond": false, "channel_status": "Users chatting about weekend plans."}}

Only return valid JSON."""
        
        # Get response from Grid API (no typing indicator during decision)
        result = await grid_client.get_answer(single_prompt, [])
        
        print(f"API Response: '{result}'")
        
        # Try to parse JSON response
        try:
            # Clean up the response to extract JSON
            result_clean = result.strip()
            if result_clean.startswith('```json'):
                result_clean = result_clean[7:]
            if result_clean.endswith('```'):
                result_clean = result_clean[:-3]
            result_clean = result_clean.strip()
            
            response_data = json.loads(result_clean)
            
            # Always update channel status if provided (even if not responding)
            new_channel_status = response_data.get("channel_status")
            if new_channel_status:
                set_channel_status(message.channel.id, channel_name, new_channel_status)
                print(f"📝 Updated #{channel_name} status: {new_channel_status}")
            
            if response_data.get("respond", False):
                response_message = response_data.get("message", "")
                react_emoji = response_data.get("react", None)
                
                # Handle reactions - check if we need to react to a previous message
                if react_emoji:
                    target_message = message  # Default to current message
                    
                    # Check if user wants to react to a previous message
                    content_lower = content.lower()
                    needs_previous = any(phrase in content_lower for phrase in [
                        'few messages ago', 'previous message', 'earlier message', 
                        'that message', 'my message', 'a few messages ago'
                    ])
                    
                    if needs_previous:
                        # Fetch recent messages to find the target
                        try:
                            messages_found = []
                            async for msg in message.channel.history(limit=20):
                                # Skip the current message and bot messages
                                if msg.id == message.id or msg.author == client.user:
                                    continue
                                messages_found.append(msg)
                            
                            # If they said "my message", find their message
                            if 'my message' in content_lower:
                                user_messages = [msg for msg in messages_found if msg.author.id == message.author.id]
                                
                                # If they also said "few messages ago", skip forward a bit
                                if 'few' in content_lower or 'several' in content_lower:
                                    # Find their message that's a few back (skip first 1-2 of their messages)
                                    skip_own = 1 if len(user_messages) > 1 else 0
                                    if len(user_messages) > skip_own:
                                        target_message = user_messages[skip_own]
                                        print(f"Found user's message {skip_own+1} back: {target_message.id} - '{target_message.content[:50]}...'")
                                    elif len(user_messages) > 0:
                                        target_message = user_messages[0]
                                        print(f"Found user's most recent message: {target_message.id} - '{target_message.content[:50]}...'")
                                else:
                                    # Just "my message" - find their most recent
                                    if len(user_messages) > 0:
                                        target_message = user_messages[0]
                                        print(f"Found user's most recent message: {target_message.id} - '{target_message.content[:50]}...'")
                            # Otherwise, find a message a few back (skip 1-3 messages)
                            else:
                                # Try to find message 2-4 messages back
                                skip_count = 2  # Default: 2 messages back
                                if 'few' in content_lower or 'several' in content_lower:
                                    skip_count = 3
                                
                                if len(messages_found) > skip_count:
                                    target_message = messages_found[skip_count]
                                    print(f"Found message {skip_count} back: {target_message.id} - '{target_message.content[:50]}...'")
                                elif len(messages_found) > 0:
                                    # Fallback to first non-bot message found
                                    target_message = messages_found[0]
                                    print(f"Found first previous message: {target_message.id} - '{target_message.content[:50]}...'")
                                    
                        except Exception as e:
                            print(f"Error fetching message history: {e}")
                    
                    try:
                        await target_message.add_reaction(react_emoji)
                        print(f"Reacted with {react_emoji} to message {target_message.id} from {target_message.author.display_name}")
                    except Exception as e:
                        print(f"Error adding reaction: {e}")
                
                if response_message:
                    # Add bot response to channel history
                    add_message(message.channel.id, BOT_NAME, response_message, author_id=client.user.id, is_bot=True)
                    
                    # Show typing indicator for 1-2 seconds before responding
                    async with message.channel.typing():
                        await asyncio.sleep(1.5)  # 1.5 second delay
                    
                    # Send the response naturally
                    await message.channel.send(response_message)
                    print(f"Responding with: '{response_message}'")
                    return True
                elif react_emoji:
                    # Only reacted, no message
                    return True
                else:
                    print("Response data has respond=true but no message or reaction")
                    return False
            else:
                print(f"Not responding to message: '{content}'")
                return False
                
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON response: {e}")
            print(f"Raw response: '{result}'")
            return False
        
    except Exception as e:
        print(f"Error in classify_and_respond: {str(e)}")
        return False

@client.event
async def on_reaction_add(reaction, user):
    """Handle reactions on ban vote messages."""
    # Ignore bot's own reactions
    if user == client.user:
        return
    
    # Check if this is a ban vote message
    if reaction.message.id not in pending_ban_votes:
        return
    
    vote_info = pending_ban_votes[reaction.message.id]
    
    # Ignore reactions from the target user
    if user.id == vote_info['target_user_id']:
        return
    
    # Handle upvote (✅)
    if str(reaction.emoji) == '✅':
        vote_info['upvotes'].add(user.id)
        print(f"✅ Upvote added for ban vote. Total: {len(vote_info['upvotes'])}/{BAN_VOTE_THRESHOLD}")
        
        # Check if threshold met
        if len(vote_info['upvotes']) >= BAN_VOTE_THRESHOLD:
            await execute_ban(reaction.message, vote_info)
    
    # Handle downvote (❌)
    elif str(reaction.emoji) == '❌':
        vote_info['downvotes'].add(user.id)
        print(f"❌ Downvote added for ban vote. Total: {len(vote_info['downvotes'])}/{DISMISS_VOTE_THRESHOLD}")
        
        # If downvotes reach threshold, dismiss
        if len(vote_info['downvotes']) >= DISMISS_VOTE_THRESHOLD:
            await reaction.message.edit(content=f"❌ Vote dismissed. {vote_info['target_user_name']} will not be banned.")
            del pending_ban_votes[reaction.message.id]

async def execute_ban(vote_message, vote_info):
    """Execute the ban after threshold is met."""
    try:
        channel = vote_message.channel
        target_user_id = vote_info['target_user_id']
        target_user_name = vote_info['target_user_name']
        reason = vote_info['reason']
        
        # Get the member object
        member = channel.guild.get_member(target_user_id)
        if not member:
            await vote_message.edit(content=f"❌ User {target_user_name} not found in server.")
            del pending_ban_votes[vote_message.id]
            return
        
        # Ban the user
        await member.ban(reason=f"Community vote: {reason}")
        
        # Update vote message
        await vote_message.edit(content=f"✅ **{target_user_name} has been banned.**\nReason: {reason}\nVotes: {len(vote_info['upvotes'])} ✅")
        
        # Clean up
        del pending_ban_votes[vote_message.id]
        
        print(f"✅ Banned {target_user_name} ({target_user_id}) - Reason: {reason}")
        
    except discord.Forbidden:
        await vote_message.edit(content=f"❌ Missing permissions to ban {target_user_name}.")
        del pending_ban_votes[vote_message.id]
    except Exception as e:
        await vote_message.edit(content=f"❌ Error banning user: {str(e)}")
        del pending_ban_votes[vote_message.id]
        print(f"Error executing ban: {e}")

@client.event
async def on_message(message):
    """Event called when a message is received."""
    import sys
    
    # Ignore messages from the bot itself
    if message.author == client.user:
        return
    
    # Handle DMs from admin for memory management
    if isinstance(message.channel, discord.DMChannel) and message.author.id == ADMIN_USER_ID:
        content = message.content.strip()
        
        if content.startswith('!memory'):
            from conversation_db import get_all_memories, save_memory, delete_memory
            parts = content.split(maxsplit=2)
            cmd = parts[1] if len(parts) > 1 else 'list'
            
            if cmd == 'list':
                memories = get_all_memories()
                if not memories:
                    await message.reply("No memories stored.")
                else:
                    mem_text = "\n".join([f"**{m['key']}**: {m['value'][:100]}{'...' if len(m['value']) > 100 else ''}" for m in memories])
                    await message.reply(f"🧠 **Memories ({len(memories)}):**\n{mem_text}")
            
            elif cmd == 'delete' and len(parts) > 2:
                key = parts[2]
                if delete_memory(key):
                    await message.reply(f"✅ Deleted memory: `{key}`")
                else:
                    await message.reply(f"❌ Memory `{key}` not found")
            
            elif cmd == 'set' and len(parts) > 2:
                # !memory set key=value
                if '=' in parts[2]:
                    key, value = parts[2].split('=', 1)
                    save_memory(key.strip(), value.strip(), source="admin DM")
                    await message.reply(f"✅ Saved: `{key.strip()}` = `{value.strip()[:50]}...`")
                else:
                    await message.reply("Usage: `!memory set key=value`")
            
            elif cmd == 'raw' and len(parts) > 2:
                key = parts[2]
                memories = get_all_memories()
                mem = next((m for m in memories if m['key'] == key), None)
                if mem:
                    await message.reply(f"**{key}**:\n```{mem['value']}```")
                else:
                    await message.reply(f"❌ Memory `{key}` not found")
            
            else:
                await message.reply("**Memory Commands:**\n`!memory list` - show all\n`!memory raw <key>` - show full text\n`!memory set key=value` - add/update\n`!memory delete <key>` - remove")
            return
        
        # Handle chattiness control
        if content.startswith('!chattiness'):
            from conversation_db import save_memory, get_memory
            parts = content.split(maxsplit=1)
            
            if len(parts) == 1:
                # Show current chattiness
                current = get_memory('chattiness_level')
                if current:
                    await message.reply(f"🗣️ Current chattiness: **{current}**")
                else:
                    await message.reply("🗣️ No chattiness level set (using default behavior)")
            else:
                try:
                    level = int(parts[1])
                    if 1 <= level <= 10:
                        save_memory('chattiness_level', str(level), source="admin DM")
                        descriptions = {
                            1: "minimal - only when directly mentioned",
                            2: "very quiet - rarely chimes in",
                            3: "quiet - selective responses",
                            4: "reserved - responds when relevant",
                            5: "balanced - moderate participation",
                            6: "engaged - regular participation",
                            7: "active - frequent responses",
                            8: "chatty - very responsive",
                            9: "very chatty - eager to participate",
                            10: "maximum - responds to almost everything"
                        }
                        desc = descriptions.get(level, "")
                        await message.reply(f"✅ Chattiness set to **{level}/10** ({desc})")
                    else:
                        await message.reply("❌ Chattiness must be between 1-10")
                except ValueError:
                    await message.reply("❌ Usage: `!chattiness <1-10>` or `!chattiness` to view current level")
            
            return
        
        # Other DM messages from admin - just acknowledge
        await message.reply("Use `!memory` commands to manage my memories, `!chattiness <1-10>` to control responsiveness, or @ me in a channel to teach me things.")
        return
    
    # Ignore channels not in our lists
    channel_name = message.channel.name if hasattr(message.channel, 'name') else 'DM'
    
    # Debug: log ALL messages to see what's coming in
    log_msg = f"📨 RAW: #{channel_name} ({message.channel.id}) from {message.author.display_name}: '{message.content[:50]}'"
    print(log_msg, flush=True)
    with open('bot.log', 'a') as f:
        f.write(log_msg + '\n')
    
    if message.channel.id not in ALL_BOT_CHANNELS:
        skip_msg = f"⏭️ SKIP: #{channel_name} ({message.channel.id}) - not in channel lists"
        print(skip_msg, flush=True)
        with open('bot.log', 'a') as f:
            f.write(skip_msg + '\n')
        return
    
    accept_msg = f"✅ ACCEPT: #{channel_name} from {message.author.display_name}"
    print(accept_msg, flush=True)
    with open('bot.log', 'a') as f:
        f.write(accept_msg + '\n')
    
    # Check for scam messages first (only in active channels)
    if message.channel.id in BOT_CHANNELS:
        if await handle_scam_detection(message):
            return  # Don't process further if scam detected
    
    # Handle document management commands in active channels
    if message.channel.id in BOT_CHANNELS:
        # Handle help command
        if message.content.startswith(COMMANDS['help']):
            await handle_help_command(message)
            return
        
        # Handle upload command
        if message.content.startswith(COMMANDS['upload']):
            await handle_upload_command(message)
            return
        
        # Handle list command
        if message.content.startswith(COMMANDS['list']):
            await handle_list_command(message)
            return
        
        # Handle delete command
        if message.content.startswith(COMMANDS['delete']):
            await handle_delete_command(message)
            return
        
        # Handle direct file uploads (if user is admin)
        if (message.author.id == ADMIN_USER_ID and 
            message.attachments and 
            not message.content.startswith('!')):
            if not message.content or message.content.isspace():
                await handle_upload_command(message)
                return
    
    # Admin @mention = store as fact
    if message.author.id == ADMIN_USER_ID and client.user.mentioned_in(message):
        # Extract the fact (remove the @mention)
        fact_text = message.content.replace(f'<@{client.user.id}>', '').strip()
        if fact_text:
            # Have AI generate a short descriptive key
            key_prompt = f"""Generate a short snake_case key (2-4 words, max 30 chars) to categorize this memory:

"{fact_text}"

Return ONLY the key, nothing else. Examples: polygon_grant_story, base_migration_info, polyvibe_details"""
            
            try:
                key = await grid_client.get_answer(key_prompt, [])
                key = key.strip().lower().replace(' ', '_')[:30]
                # Fallback if AI returns something weird
                if not key or len(key) < 3 or ' ' in key:
                    words = fact_text.split()[:3]
                    key = '_'.join(words).lower()[:30]
            except:
                words = fact_text.split()[:3]
                key = '_'.join(words).lower()[:30]
            
            # Save to memory
            from conversation_db import save_memory
            save_memory(key, fact_text, source=f"admin ({message.author.display_name})")
            
            await message.add_reaction('🧠')
            await message.reply(f"Got it! Saved as `{key}`", mention_author=False)
            print(f"💾 Admin fact stored: {key} = {fact_text[:50]}...")
            return
    
    # Process message (stores to DB, optionally responds)
    # classify_and_respond will check if channel is readonly
    await classify_and_respond(message)

if __name__ == "__main__":
    client.run(DISCORD_TOKEN) 