import asyncio
from typing import Dict, Set, Optional
from collections import defaultdict
from telethon import TelegramClient

clients_pool: Dict[TelegramClient, Optional[int]] = {}
client_locks: Dict[TelegramClient, asyncio.Lock] = {}
sender_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
message_id_mapping: Dict[int, int] = {}
cloned_users: Set[int] = set()