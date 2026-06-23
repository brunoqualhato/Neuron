import asyncio
import io
import urllib.error
from unittest.mock import patch

import pytest

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


def test_send_usa_parse_mode_html_e_converte_markdown():
    """O texto vai convertido para HTML com parse_mode=HTML (formatacao no chat)."""
    async def cenario():
        canal = TelegramChannel(MessageBus(), token="t")
        with patch.object(canal, "_api_call", return_value={"ok": True}) as mock_api:
            await canal.send(
                OutboundMessage(texto="isto e **forte**", canal="telegram", chat_id="1")
            )
        return mock_api

    mock_api = asyncio.run(cenario())
    _, params = mock_api.call_args[0]
    assert params["parse_mode"] == "HTML"
    assert params["text"] == "isto e <b>forte</b>"


def test_send_fallback_texto_puro_quando_html_falha():
    """Se o Telegram rejeitar as entidades HTML, reenvia o texto original cru."""
    async def cenario():
        canal = TelegramChannel(MessageBus(), token="t")
        respostas = [
            {"ok": False, "error_code": 400,
             "description": "Bad Request: can't parse entities: ..."},
            {"ok": True},
        ]
        with patch.object(canal, "_api_call", side_effect=respostas) as mock_api:
            await canal.send(
                OutboundMessage(texto="ola mundo", canal="telegram", chat_id="1")
            )
        return mock_api

    mock_api = asyncio.run(cenario())
    assert mock_api.call_count == 2
    _, params2 = mock_api.call_args_list[1][0]
    assert params2["text"] == "ola mundo"
    assert "parse_mode" not in params2


def test_send_nao_faz_fallback_em_erro_que_nao_e_de_parse():
    """Erro logico comum (chat not found) levanta direto, sem reenviar."""
    async def cenario():
        canal = TelegramChannel(MessageBus(), token="t")
        with patch.object(
            canal, "_api_call",
            return_value={"ok": False, "description": "chat not found"},
        ) as mock_api:
            try:
                await canal.send(
                    OutboundMessage(texto="oi", canal="telegram", chat_id="999")
                )
            except RuntimeError:
                pass
        return mock_api

    mock_api = asyncio.run(cenario())
    assert mock_api.call_count == 1  # nao tentou fallback


def test_api_call_trata_http_error_retornando_json():
    """HTTPError (401/4xx) nao deve estourar: retorna o JSON de erro do Telegram."""
    corpo = b'{"ok":false,"error_code":401,"description":"Unauthorized"}'
    err = urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, io.BytesIO(corpo))
    canal = TelegramChannel(MessageBus(), token="t")
    with patch("urllib.request.urlopen", side_effect=err):
        resp = canal._api_call("getMe", {})
    assert resp["ok"] is False
    assert resp["error_code"] == 401


def test_send_levanta_quando_ok_false():
    """send deve levantar em erro logico para o ChannelManager re-tentar."""
    async def cenario():
        canal = TelegramChannel(MessageBus(), token="t")
        with patch.object(canal, "_api_call", return_value={"ok": False, "description": "chat not found"}):
            await canal.send(OutboundMessage(texto="oi", canal="telegram", chat_id="999"))

    with pytest.raises(RuntimeError):
        asyncio.run(cenario())


def test_start_para_em_erro_fatal_sem_loop():
    """getUpdates com 401 (fatal) para o canal em vez de entrar em loop infinito."""
    async def cenario():
        canal = TelegramChannel(MessageBus(), token="t")
        with patch.object(
            canal, "_api_call",
            return_value={"ok": False, "error_code": 401, "description": "Unauthorized"},
        ):
            await asyncio.wait_for(canal.start(), timeout=2)
        return canal._rodando

    assert asyncio.run(cenario()) is False
