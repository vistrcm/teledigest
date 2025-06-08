from telethon import TelegramClient
from telethon.tl import types
import os
import asyncio
import logging
from data import Storage
from telethon.sessions import StringSession
import pyrage
from openai import AsyncOpenAI
import textwrap

logger = logging.getLogger(__name__)

RETRIEVE_LIMIT = 2  # number of messages to tetrieve if no data

try:
    API_ID = int(os.environ["API_ID"])
    API_HASH = os.environ["API_HASH"]
    AGE_KEY = os.environ["AGE_KEY"]
    IDENTITY = pyrage.x25519.Identity.from_str(AGE_KEY)
    OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
except KeyError:
    print("Please set required environment variables")
    exit(1)
except ValueError:
    print("API_ID must be an integer")
    exit(2)

storage = Storage("data", IDENTITY)
session = storage.get_session()
client = TelegramClient(session, API_ID, API_HASH)
oai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

system_prompt = """
You are a specialized Telegram message summarizer for digesting channel and chat content.
You will receive raw messages delimited by '=-=-=-=-=' from a single Telegram source.

## Language Detection & Response
CRITICAL: Analyze the language distribution of the messages and respond in the SAME language:
- Russian messages → Russian summary
- Ukrainian messages → Ukrainian summary  
- English messages → English summary
- Mixed languages → Use the most frequent language (>50% of content)
- Equal distribution → Use the language of the most recent/important messages

## Content Analysis Process
1. **Identify Content Types**: Distinguish between news, discussions, technical content, announcements, and casual conversation
2. **Extract Key Information**: Focus on actionable items, important updates, decisions, and significant developments
3. **Handle Duplicates**: Merge repeated information, prioritize corrections over original statements
4. **Preserve Context**: Maintain meaningful tone, urgency, and emotional context when relevant

## Media Content Handling
Process these media markers and include them strategically:
- `[PHOTO]` - Visual content, include if it adds context to the discussion
- `[VIDEO: filename]` - Video content, mention if it's instructional or newsworthy
- `[AUDIO: filename]` - Audio messages, include if they contain important information
- `[FILE: filename]` - Documents/files, always mention as they're usually important
- `[LOCATION]` - Location sharing, include if relevant to the topic
- `[CONTACT]` - Contact information, include if it's being shared for a purpose
- `[POLL: question]` - Polls, summarize the question and context
- `[WEBPAGE: title]` - Web links, include if they're reference material or news sources

## Technical Content
- Preserve code snippets with proper formatting
- Include technical URLs and documentation links
- Maintain technical terminology and version numbers
- Summarize technical discussions while preserving key details

## Output Structure
Organize your summary with:
- **Main developments/news** (most important content first)
- **Key decisions or outcomes**
- **Important links, resources, or media** (with message URLs for reference)
- **Notable discussions or debates** (if significant)
- **Action items or next steps** (if any)

## Reference Requirements
- Include message URLs (https://t.me/username/message_id) for the most important points
- Reference specific media attachments when they're central to the discussion
- Link to external resources mentioned in messages

## Quality Standards
- Ignore trivial messages (greetings, emoji-only, off-topic chatter)
- Combine related messages into coherent points
- Prioritize recent information over older contradicted information
- Maintain chronological flow when it matters for understanding
- Keep technical accuracy for code, links, and specific details

Present only the final summary without revealing your analysis process.
"""


async def summary(oai, content, images=None):
    if not content:
        return None

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]

    # If we have images, add them to the message
    if images and len(images) > 0:
        # Create a message with text and image content
        content_parts = [{"type": "text", "text": content}]

        # Add each image as content
        for img_data in images:
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_data}",
                    "detail": "low"  # Use low detail to save tokens
                }
            })

        messages.append({"role": "user", "content": content_parts})
    else:
        # Just text, no images
        messages.append({"role": "user", "content": content})

    completion = await oai.chat.completions.create(
        model="gpt-4.1",
        n=1,  # only one completion
        messages=messages,
    )

    return completion.choices[0].message.content


def new_history(last_known_msg):
    return last_known_msg is None


def iter_recent(client, entity):
    return client.iter_messages(entity, limit=RETRIEVE_LIMIT)


def iter_since(client, entity, last_known_msg):
    return client.iter_messages(entity, min_id=last_known_msg)


def get_messages_fn(client, entity, last_known_msg):
    logger.debug("last known message for %s: %s", entity, last_known_msg)
    if new_history(last_known_msg):
        logger.info("new history for %s", entity)
        return iter_recent(client, entity)
    return iter_since(client, entity, last_known_msg)


def newest_message(latest_msg_id, new_msg_id):
    if latest_msg_id is None:
        return new_msg_id
    return max(latest_msg_id, new_msg_id)


def messages2text(messages):
    formatted_parts = []
    for msg in messages:
        id = msg["id"]
        username = msg["username"]
        text = msg["text"]
        url = f"https://t.me/{username}/{id}"
        formatted_parts.append(f"url: {url}\nusername: {username}\n text:{text}")

    return "\n=-=-=-=-=\n".join(formatted_parts)


async def get_dialogs(client):
    dialogs = []
    async for dialog in client.iter_dialogs():
        dialogs.append({"id": dialog.id, "name": dialog.name})
    return dialogs


async def get_username(message):
    chat = await message.get_chat()
    return chat.username


def get_media_description(message):
    """Extract media information from a message."""
    if not message.media:
        return None

    if isinstance(message.media, types.MessageMediaPhoto):
        return "[PHOTO]"

    elif isinstance(message.media, types.MessageMediaDocument):
        doc = message.media.document
        file_name = None

        # Extract filename from attributes
        for attr in doc.attributes:
            if isinstance(attr, types.DocumentAttributeFilename):
                file_name = attr.file_name
                break

        # Check for video
        is_video = any(isinstance(attr, types.DocumentAttributeVideo) for attr in doc.attributes)
        if is_video:
            return f"[VIDEO{': ' + file_name if file_name else ''}]"

        # Check for audio
        is_audio = any(isinstance(attr, types.DocumentAttributeAudio) for attr in doc.attributes)
        if is_audio:
            return f"[AUDIO{': ' + file_name if file_name else ''}]"

        # Generic document
        return f"[FILE{': ' + file_name if file_name else ''}]"

    elif isinstance(message.media, types.MessageMediaGeo):
        return "[LOCATION]"

    elif isinstance(message.media, types.MessageMediaContact):
        return "[CONTACT]"

    elif isinstance(message.media, types.MessageMediaPoll):
        return f"[POLL: {message.media.poll.question}]"

    elif isinstance(message.media, types.MessageMediaWebPage):
        return f"[WEBPAGE: {message.media.webpage.title if hasattr(message.media.webpage, 'title') else ''}]"

    return "[MEDIA]"

async def process_entity(entity):
    logger.info("processing: '%s'", entity)
    entity_path = storage.messages / str(entity)
    entity_path.mkdir(parents=True, exist_ok=True)
    photos_dir = entity_path / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    latest_msg_id = await storage.get_last_known_msg(entity)
    tasks = []
    messages = []
    photo_tasks = []

    async for message in get_messages_fn(client, entity, latest_msg_id):
        latest_msg_id = newest_message(latest_msg_id, message.id)

        logger.debug("id: %s: %s", message.id, message.text)
        tasks.append(message.mark_read())

        # Get message content
        content = message.text or ""
        media_desc = get_media_description(message)

        # Skip messages with no content
        if not content and not media_desc:
            logger.debug("message %s has no content", message)
            continue

        # Combine text and media description
        if media_desc:
            content = f"{media_desc}\n{content}" if content else media_desc

        tasks.append(storage.write_message(entity_path, message, content))

        # If message has a photo, download and store it encrypted
        if isinstance(message.media, types.MessageMediaPhoto):
            photo_path = photos_dir / f"photo_{message.id}.jpg.age"
            # Queue photo download and encryption task
            photo_task = asyncio.create_task(
                storage.download_and_encrypt_media(message, photo_path)
            )
            photo_tasks.append(photo_task)

        username = await get_username(message)
        messages.append(
            {
                "id": message.id,
                "entity": entity,
                "username": username,
                "text": content,
            }
        )
    tasks.append(storage.write_last_known_msg(entity, latest_msg_id))

    # Process all tasks
    if tasks:
        logger.debug("waiting tasks to complete")
        await asyncio.gather(*tasks)

    # Process photo tasks
    if photo_tasks:
        logger.debug("waiting for photo tasks to complete")
        await asyncio.gather(*photo_tasks)

    # Generate summary
    summary_request = messages2text(reversed(messages))

    # Process photos for the summary if needed
    # For now, we're just including text descriptions of photos in the summary
    # In a future enhancement, we could decrypt and send photos to OpenAI for analysis

    return await summary(oai_client, summary_request)


def print_wrapped(text):
    terminal_size = os.get_terminal_size().columns

    wrapped_text = "\n".join(
        [textwrap.fill(line, terminal_size, replace_whitespace=False) for line in text.splitlines()]
    )

    print(wrapped_text)

async def main():
    logging.basicConfig(level=logging.WARN)

    for dialog in await get_dialogs(client):
        entity = dialog["id"]

        if summary_response := await process_entity(entity):
            print(f"📰 {dialog['name']}:")
            print_wrapped(summary_response)
            print()
            print("*" * os.get_terminal_size().columns)  # separator
            print()

    session_string = StringSession.save(client.session)
    await storage.save_session(session_string)


with client:
    client.loop.run_until_complete(main())
