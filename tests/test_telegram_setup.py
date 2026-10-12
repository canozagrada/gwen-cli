"""`gwen setup telegram` against a fake Telegram Bot API."""

from __future__ import annotations

import pytest
from aiohttp import web

from conftest import run

from gwen_cli import cli, telegram_setup

TOKEN = "123456789:AAH" + "x" * 32


def update(update_id, chat_id, first_name="Marco", kind="private", **extra):
    chat = {"id": chat_id, "type": kind, "first_name": first_name, **extra}
    return {
        "update_id": update_id,
        "message": {"message_id": 1, "chat": chat, "text": "/start"},
    }


class FakeTelegram:
    """Answers getMe/getUpdates/sendMessage; updates appear after `delay` polls."""

    def __init__(self, updates=(), delay=0, token=TOKEN, webhook=False):
        self.updates = list(updates)
        self.delay = delay
        self.token = token
        self.webhook = webhook
        self.polls = 0
        self.sent: list[dict] = []

    async def handle(self, request):
        token, method = request.match_info["token"], request.match_info["method"]
        if token != f"bot{self.token}":
            return web.json_response(
                {"ok": False, "error_code": 401, "description": "Unauthorized"},
                status=401,
            )
        body = await request.json()
        if method == "getMe":
            return web.json_response(
                {
                    "ok": True,
                    "result": {"id": 1, "is_bot": True, "username": "GwenStatusBot"},
                }
            )
        if method == "getUpdates":
            if self.webhook:
                return web.json_response(
                    {
                        "ok": False,
                        "error_code": 409,
                        "description": "Conflict: can't use getUpdates method while webhook is active",
                    },
                    status=409,
                )
            self.polls += 1
            ready = self.updates if self.polls > self.delay else []
            offset = body.get("offset") or 0
            return web.json_response(
                {"ok": True, "result": [u for u in ready if u["update_id"] >= offset]}
            )
        if method == "sendMessage":
            self.sent.append(body)
            return web.json_response({"ok": True, "result": {"message_id": 2}})
        return web.json_response({"ok": False, "description": "Not Found"}, status=404)


def connect(fake, token=TOKEN, choose=None, patience=5):
    lines: list[str] = []

    async def scenario():
        app = web.Application()
        app.router.add_post("/{token}/{method}", fake.handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            return await telegram_setup.connect(
                token,
                lines.append,
                choose or (lambda chats: pytest.fail("asked to choose")),
                api=f"http://127.0.0.1:{port}",
                patience=patience,
            )
        finally:
            await runner.cleanup()

    return run(scenario()), lines


def test_finds_the_chat_and_sends_a_test_message():
    fake = FakeTelegram([update(10, 4242)])
    (username, chat), lines = connect(fake)

    assert username == "GwenStatusBot"
    assert chat == telegram_setup.Chat(4242, "Marco", "private")
    assert fake.sent == [{"chat_id": 4242, "text": telegram_setup.TEST_MESSAGE}]
    assert lines == ["Token works: this is @GwenStatusBot."]


def test_waits_for_the_person_to_press_start(monkeypatch):
    fake = FakeTelegram([update(10, 4242)], delay=2)
    (_, chat), lines = connect(fake)

    assert chat.id == 4242
    assert any("https://t.me/GwenStatusBot" in line for line in lines)
    assert fake.polls >= 3


def test_gives_up_if_nobody_presses_start():
    with pytest.raises(telegram_setup.SetupError, match="Press Start"):
        connect(FakeTelegram(), patience=1)


def test_several_chats_ask_which_one():
    fake = FakeTelegram(
        [update(10, 1, "Marco"), update(11, -100500, kind="group", title="Ops")]
    )
    picked = []

    def choose(chats):
        picked.extend(chats)
        return chats[1]

    (_, chat), _ = connect(fake, choose=choose)
    assert [c.name for c in picked] == ["Marco", "Ops"]
    assert chat.id == -100500 and fake.sent[0]["chat_id"] == -100500


def test_wrong_token_says_so_without_echoing_it():
    other = "987654321:BBH" + "y" * 32
    with pytest.raises(telegram_setup.SetupError) as raised:
        connect(FakeTelegram(token=TOKEN), token=other)
    assert "did not accept that token" in str(raised.value)
    assert "y" * 32 not in str(raised.value)


def test_existing_webhook_is_left_alone():
    with pytest.raises(telegram_setup.SetupError, match="webhook"):
        connect(FakeTelegram(webhook=True))


def test_network_errors_hide_the_token():
    async def scenario():
        await telegram_setup.connect(
            TOKEN, print, None, api="http://127.0.0.1:9", patience=1
        )

    with pytest.raises(telegram_setup.SetupError) as raised:
        run(scenario())
    assert TOKEN not in str(raised.value)


@pytest.mark.parametrize(
    "token,ok",
    [
        (TOKEN, True),
        (" " + TOKEN + " ", True),
        ("hello", False),
        ("123:short", False),
        ("", False),
    ],
)
def test_token_shape(token, ok):
    assert telegram_setup.looks_like_token(token) is ok


def test_setup_command(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(telegram_setup.TOKEN_VAR, raising=False)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: TOKEN)
    saved = {}

    async def fake_connect(token, say, choose, **_):
        say("Token works: this is @GwenStatusBot.")
        return "GwenStatusBot", telegram_setup.Chat(4242, "Marco", "private")

    monkeypatch.setattr(telegram_setup, "connect", fake_connect)
    monkeypatch.setattr(
        telegram_setup,
        "save",
        lambda token, chat: saved.update(token=token, chat=chat) or "a test place",
    )
    monkeypatch.setattr("sys.argv", ["gwen", "setup", "telegram"])

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "BotFather" in out and "Connected." in out and "a test place" in out
    assert TOKEN not in out
    assert saved == {"token": TOKEN, "chat": 4242}


def test_setup_reuses_a_saved_token(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(telegram_setup.TOKEN_VAR, TOKEN)
    monkeypatch.setattr(
        cli.getpass, "getpass", lambda prompt: pytest.fail("should not ask")
    )

    async def fake_connect(token, say, choose, **_):
        assert token == TOKEN
        return "GwenStatusBot", telegram_setup.Chat(1, "Marco", "private")

    monkeypatch.setattr(telegram_setup, "connect", fake_connect)
    monkeypatch.setattr(telegram_setup, "save", lambda token, chat: "")
    monkeypatch.setattr("sys.argv", ["gwen", "setup", "telegram"])

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "already saved" in out
    assert "GWEN_TELEGRAM_CHAT=1" in out, "without a place to save, say what to set"


def test_setup_gives_up_after_three_bad_tokens(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(telegram_setup.TOKEN_VAR, raising=False)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "nope")
    monkeypatch.setattr("sys.argv", ["gwen", "setup", "telegram"])
    assert cli.main() == 2
