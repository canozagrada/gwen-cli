"""`gwen setup telegram`: connect a Telegram bot in one step.

The manual route -- copy a token, open getUpdates in a browser, dig the chat
id out of JSON, set two environment variables -- is where people give up.
This does the middle part for them:

1. Read the bot token without echoing it, and check it with Telegram.
2. Ask them to press Start in the bot's chat, and wait for that message.
3. Send a test message to the chat it came from.
4. Save the token and chat id where `gwen watch` reads them.

Creating the bot with @BotFather is the one step left to the person: Telegram
only hands out tokens to people.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from dataclasses import dataclass

import aiohttp

API = "https://api.telegram.org"
_TIMEOUT = aiohttp.ClientTimeout(total=40, connect=10)
_TOKEN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")

TOKEN_VAR = "GWEN_TELEGRAM_TOKEN"
CHAT_VAR = "GWEN_TELEGRAM_CHAT"


class SetupError(RuntimeError):
    """Telegram refused, or the person never pressed Start."""


@dataclass(frozen=True)
class Chat:
    id: int
    name: str
    kind: str


def looks_like_token(token: str) -> bool:
    return bool(_TOKEN.match(token.strip()))


class Bot:
    def __init__(self, token: str, api: str = API):
        self.token = token.strip()
        self.api = api.rstrip("/")

    async def call(self, session: aiohttp.ClientSession, method: str, **params):
        try:
            async with session.post(
                f"{self.api}/bot{self.token}/{method}", json=params
            ) as response:
                try:
                    data = await response.json(content_type=None)
                except ValueError:
                    data = {}
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            # The token is in the URL; keep it out of anything printed.
            raise SetupError(
                f"could not reach Telegram: {str(exc).replace(self.token, '<token>') or 'timed out'}"
            ) from None
        if not data.get("ok"):
            raise SetupError(
                data.get("description") or f"Telegram returned HTTP {response.status}"
            )
        return data["result"]

    async def name(self, session) -> str:
        """The bot's @username; also proves the token works."""
        try:
            me = await self.call(session, "getMe")
        except SetupError as exc:
            if "unauthorized" in str(exc).lower() or "not found" in str(exc).lower():
                raise SetupError(
                    "Telegram did not accept that token. Copy it again from @BotFather."
                ) from None
            raise
        return me["username"]

    async def chats(
        self, session, offset: int | None = None, wait: int = 0
    ) -> tuple[list[Chat], int | None]:
        """Chats that have messaged the bot, and the next update offset."""
        params = {
            "timeout": wait,
            "allowed_updates": ["message", "my_chat_member", "channel_post"],
        }
        if offset is not None:
            params["offset"] = offset
        try:
            updates = await self.call(session, "getUpdates", **params)
        except SetupError as exc:
            if "webhook" in str(exc).lower():
                # Removing it would break whatever else uses this bot, so ask.
                raise SetupError(
                    "This bot already sends its messages to another tool (it has a webhook). "
                    "Create a separate bot for GWEN with @BotFather, or remove the webhook "
                    "if nothing uses it any more."
                ) from None
            raise
        found: dict[int, Chat] = {}
        for update in updates:
            for key in ("message", "my_chat_member", "channel_post"):
                chat = (update.get(key) or {}).get("chat")
                if chat:
                    name = (
                        chat.get("title")
                        or " ".join(
                            filter(
                                None, [chat.get("first_name"), chat.get("last_name")]
                            )
                        )
                        or chat.get("username")
                        or str(chat["id"])
                    )
                    found[chat["id"]] = Chat(
                        chat["id"], name, chat.get("type", "private")
                    )
        next_offset = updates[-1]["update_id"] + 1 if updates else offset
        return list(found.values()), next_offset

    async def send(self, session, chat_id: int, text: str) -> None:
        await self.call(session, "sendMessage", chat_id=chat_id, text=text)


async def find_chats(bot: Bot, session, patience: float, poll: int = 20) -> list[Chat]:
    """Chats that messaged the bot, waiting up to *patience* seconds for one."""
    chats, offset = await bot.chats(session)
    deadline = time.monotonic() + patience
    while not chats and time.monotonic() < deadline:
        wait = max(1, min(poll, int(deadline - time.monotonic())))
        chats, offset = await bot.chats(session, offset, wait)
    return chats


TEST_MESSAGE = (
    "✅ GWEN is connected.\n"
    "Cloud status changes you care about will arrive in this chat."
)


async def connect(
    token: str,
    say,
    choose,
    api: str = API,
    patience: float = 180,
) -> tuple[str, Chat]:
    """Check the token, find the chat, send a test. Returns (bot username, chat).

    *say* prints a line; *choose* picks one of several chats and returns it.
    """
    bot = Bot(token, api)
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        username = await bot.name(session)
        say(f"Token works: this is @{username}.")

        chats, _ = await bot.chats(session)
        if not chats:
            say(
                f"Now open https://t.me/{username} in Telegram and press Start (or send it any message)."
            )
            say("Waiting for that message...")
            chats = await find_chats(bot, session, patience)
        if not chats:
            raise SetupError(
                f"No message reached @{username} in {int(patience // 60)} minutes. "
                "Press Start in its chat, then run 'gwen setup telegram' again."
            )

        chat = chats[0] if len(chats) == 1 else choose(chats)
        await bot.send(session, chat.id, TEST_MESSAGE)
    return username, chat


def save(token: str, chat_id: int) -> str:
    """Store both values where `gwen watch` reads them. Returns where that was."""
    os.environ[TOKEN_VAR] = token
    os.environ[CHAT_VAR] = str(chat_id)
    if sys.platform == "win32":
        _save_windows({TOKEN_VAR: token, CHAT_VAR: str(chat_id)})
        return "your Windows user environment variables"
    return ""


def _save_windows(values: dict[str, str]) -> None:  # pragma: no cover - Windows only
    import ctypes
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
    ) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    # Tell Explorer, so terminals and tasks started from now on see the change.
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", SMTO_ABORTIFHUNG, 5000, None
    )
