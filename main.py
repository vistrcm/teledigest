from telethon import TelegramClient
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
You are given a set of raw messages from a single Telegram channel or chat.
These messages may include news, important events, article reviews, casual chatter, jokes, pretty much anything.
The messages may be in different languages, mostly English, Russian and Ukranian.
Each message is separated by '=-=-=-=-='.

Your task is to produce a summary (a short, readable digest) that highlights the most important ideas, topics and urgent news or events from these messages, and excludes unnecessasry information.

For any important messages mentioned, include a reference link if provided in the input.
If the input contains no link, skip that detail.

Make sure the summary:
 * Is short but informative, focusing on key updates and events.
 * Use same language as original input messages (English, Ukranian or Russian).
 * Provides references (links) if available.
 * Omits any trivial or non-newsworthy content.
 * Do not include any hashtags.
 * Do not mention any references to “foreign agents” or related nonsense. If message include disclamer like "НАСТОЯЩИЙ МАТЕРИАЛ (ИНФОРМАЦИЯ) ПРОИЗВЕДЁН, РАСПРОСТРАНЕН И (ИЛИ) НАПРАВЛЕН ИНОСТРАННЫМ АГЕНТОМ"
 * If multiple messages are related or looks like a conversation, write a digest of the conversation, not single message.
 * Use the same tone and style as the messages, make it looks like it was written by the same author.
"""


async def summary(oai, content):
    if not content:
        return None

    completion = await oai.chat.completions.create(
        model="gpt-4o",
        n=1,  # only one completion
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {"role": "user", "content": content},
        ],
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
        formatted_parts.append(f"message url: {url}\n{text}")

    return "\n=-=-=-=-=\n".join(formatted_parts)


async def get_dialogs(client):
    dialogs = []
    async for dialog in client.iter_dialogs():
        dialogs.append({"id": dialog.id, "name": dialog.name})
    return dialogs


async def get_username(message):
    chat = await message.get_chat()
    return chat.username


async def process_entity(entity):
    logger.info("processing: '%s'", entity)
    entity_path = storage.messages / str(entity)
    entity_path.mkdir(parents=True, exist_ok=True)
    latest_msg_id = await storage.get_last_known_msg(entity)
    tasks = []
    messages = []
    async for message in get_messages_fn(client, entity, latest_msg_id):
        latest_msg_id = newest_message(latest_msg_id, message.id)

        logger.debug("id: %s: %s", message.id, message.text)
        tasks.append(message.mark_read())
        if not message.text:
            logger.debug("message %s has no text", message)
            continue
        tasks.append(storage.write_message(entity_path, message))
        username = await get_username(message)
        messages.append(
            {
                "id": message.id,
                "entity": entity,
                "username": username,
                "text": message.text,
            }
        )
    tasks.append(storage.write_last_known_msg(entity, latest_msg_id))

    if tasks:
        logger.debug("waiting tasks to complete")
        await asyncio.gather(*tasks)

    summary_request = messages2text(reversed(messages))
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
        print(f"telegram dialog: {dialog['name']}:")
        entity = dialog["id"]

        if summary_response := await process_entity(entity):
            print_wrapped(summary_response)

            print()
            print("*" * 80)  # separator
            print()

    session_string = StringSession.save(client.session)
    await storage.save_session(session_string)


with client:
    client.loop.run_until_complete(main())
