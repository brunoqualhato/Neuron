"""Canal Telegram via Bot API (long-polling), sem dependência externa (urllib)."""
from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request

from src.conexoes.bus import InboundMessage, MessageBus, OutboundMessage, SenderInfo
from src.conexoes.channels.base import BaseChannel
from src.conexoes.channels.registry import registrar

_API = "https://api.telegram.org/bot{token}/{metodo}"


class TelegramChannel(BaseChannel):
    def __init__(
        self,
        bus: MessageBus,
        *,
        token: str,
        nome: str = "telegram",
        allow_list=None,
        max_message_length: int = 4096,
    ) -> None:
        super().__init__(bus, nome=nome, allow_list=allow_list,
                         max_message_length=max_message_length)
        self._token = token
        self._rodando = False
        self._offset = 0

    def _api_call(self, metodo: str, params: dict) -> dict:
        url = _API.format(token=self._token, metodo=metodo)
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(url, data=data, timeout=65) as resp:  # noqa: S310
            return json.loads(resp.read().decode())

    def _inbound_de_update(self, update: dict) -> InboundMessage | None:
        msg = update.get("message") or {}
        texto = msg.get("text")
        if not texto:
            return None
        remetente = msg.get("from", {})
        sender = SenderInfo(
            id=str(remetente.get("id", "")),
            nome=remetente.get("first_name", ""),
            canal=self.nome,
        )
        if not self.is_allowed_sender(sender):
            return None
        return InboundMessage(
            texto=texto,
            sender=sender,
            canal=self.nome,
            chat_id=str(msg.get("chat", {}).get("id", "")),
        )

    async def send(self, msg: OutboundMessage) -> None:
        await asyncio.to_thread(
            self._api_call, "sendMessage", {"chat_id": msg.chat_id, "text": msg.texto}
        )

    async def start(self) -> None:
        self._rodando = True
        while self._rodando:
            resp = await asyncio.to_thread(
                self._api_call, "getUpdates", {"offset": self._offset, "timeout": 60}
            )
            for update in resp.get("result", []):
                self._offset = update["update_id"] + 1
                inbound = self._inbound_de_update(update)
                if inbound is not None:
                    await self._bus.publicar_entrada(inbound)

    async def stop(self) -> None:
        self._rodando = False


registrar("telegram", lambda bus, cfg: TelegramChannel(
    bus, token=cfg["token"], allow_list=cfg.get("allow_list")
))
