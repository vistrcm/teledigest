from telethon import TelegramClient
import os
import asyncio
import logging
from data import Storage
from telethon.sessions import StringSession
import pyrage
from openai import AsyncOpenAI

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
You are a helpful assistant. You are asked to summarize the following Telegram messages.
Each message is separated by '=-=-=-=-='.
Summarize them into a concise paragraph or a few bullet points, using the same language as the original messages.

Please follow these rules:
1.	Do not include any hashtags in your summary.
2.	Do not mention any references to “foreign agents” or related nonsense.
3.	If multiple messages are related or form a conversation, summarize them together.
4.	Include URLs to messages when appropriate.
5.	Focus on main news and central discussion points, omit minor details.
6.	Maintain the original language of each message in your summary.
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


async def main():
    logging.basicConfig(level=logging.WARN)

    for dialog in await get_dialogs(client):
        print(f"telegram dialog: {dialog['name']}:")
        entity = dialog["id"]

        if summary_response := await process_entity(entity):
            print(summary_response)

            print()
            print("*" * 80)  # separator
            print()

    session_string = StringSession.save(client.session)
    await storage.save_session(session_string)


with client:
    client.loop.run_until_complete(main())
