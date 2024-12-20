from pathlib import Path
import pyrage
import asyncio
from typing import Union
from telethon.sessions import StringSession


class Storage:
    def __init__(self, data_path, identity):
        self.data = Path(data_path)
        self.messages = self.data / "messages"
        self.sessions = self.data / "sessions"
        self.identity = identity
        self.pubkey = identity.to_public()

    def sync_read_data(self, path):
        with open(path, "rb") as fl:
            encrypted = fl.read()
            decrypted = pyrage.decrypt(encrypted, [self.identity])
            decoded = decrypted.decode("utf-8", errors="strict")
            return decoded

    async def read_data(self, path):
        return await asyncio.to_thread(self.sync_read_data, path)

    async def write_data(self, path: Union[Path, str], data: str):
        def sync_write_data(path: str, data: str):
            binary = data.encode("utf-8", errors="strict")
            encrypted = pyrage.encrypt(binary, [self.pubkey])
            with open(path, "wb") as fl:
                fl.write(encrypted)

        return await asyncio.to_thread(sync_write_data, path, data)

    def _session_path(self):
        return self.sessions / "test.session.age"

    def get_session(self):
        session_file = self._session_path()
        if not session_file.exists():
            return StringSession()
        return StringSession(self.sync_read_data(session_file))

    def _meta_last_msg_path(self, entity):
        return self.messages / str(entity) / "meta.latest_msg.txt.age"

    async def get_last_known_msg(self, entity):
        meta_last = self._meta_last_msg_path(entity)
        if not meta_last.exists():
            return None
        return int(await self.read_data(meta_last))

    async def write_last_known_msg(self, entity, latest_msg_id):
        await self.write_data(self._meta_last_msg_path(entity), str(latest_msg_id))

    async def write_message(self, entity_path, message):
        file_path = entity_path / f"msg.{message.id}.txt.age"
        await self.write_data(file_path, message.text)

    async def save_session(self, session):
        path = self._session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.write_data(path, session)
