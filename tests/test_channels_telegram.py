import asyncio
from unittest.mock import patch
from src.conexoes.bus import MessageBus, OutboundMessage
from src.conexoes.channels.telegram import TelegramChannel


def test_parse_update_vira_inbound():
    bus = MessageBus()
    canal = TelegramChannel(bus, token="t")
    update = {
        "message": {
            "text": "oi bot",
            "chat": {"id": 123},
            "from": {"id": 99, "first_name": "Nik"},
        }
    }
    msg = canal._inbound_de_update(update)
    assert msg is not None
    assert msg.texto == "oi bot"
    assert msg.chat_id == "123"
    assert msg.sender.id == "99"
    assert msg.canal == "telegram"


def test_allow_list_bloqueia_update():
    bus = MessageBus()
    canal = TelegramChannel(bus, token="t", allow_list=["1"])
    update = {"message": {"text": "x", "chat": {"id": 5}, "from": {"id": 99}}}
    assert canal._inbound_de_update(update) is None


def test_send_chama_sendmessage():
    async def cenario():
        bus = MessageBus()
        canal = TelegramChannel(bus, token="t")
        with patch.object(canal, "_api_call", return_value={"ok": True}) as mock_api:
            await canal.send(OutboundMessage(texto="oi", canal="telegram", chat_id="123"))
        return mock_api

    mock_api = asyncio.run(cenario())
    metodo, params = mock_api.call_args[0]
    assert metodo == "sendMessage"
    assert params["chat_id"] == "123"
    assert params["text"] == "oi"
