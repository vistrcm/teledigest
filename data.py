from pathlib import Path
import pyrage
import asyncio
from typing import Union
from telethon.sessions import StringSession
from io import BytesIO


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

    async def write_message(self, entity_path, message, content=None):
        file_path = entity_path / f"msg.{message.id}.txt.age"
        # Use provided content if available, otherwise use message.text
        text_to_write = content if content is not None else message.text
        await self.write_data(file_path, text_to_write)

    async def save_session(self, session):
        path = self._session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.write_data(path, session)
        
    async def download_and_encrypt_media(self, message, target_path):
        """Download media to memory, encrypt it, and save to disk."""
        # Download media to memory buffer
        buffer = BytesIO()
        await message.download_media(file=buffer)
        
        # Reset buffer pointer to start
        buffer.seek(0)
        
        # Get binary data from buffer
        media_data = buffer.read()
        
        # Encrypt the data
        encrypted_data = pyrage.encrypt(media_data, [self.pubkey])
        
        # Write the encrypted data to file
        with open(target_path, "wb") as encrypted_file:
            encrypted_file.write(encrypted_data)
            
    async def decrypt_media(self, file_path):
        """Decrypt media file and return the binary data."""
        with open(file_path, "rb") as encrypted_file:
            encrypted_data = encrypted_file.read()
            
        # Decrypt and return the data
        return pyrage.decrypt(encrypted_data, [self.identity])
