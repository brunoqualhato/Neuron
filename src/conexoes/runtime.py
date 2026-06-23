"""Liga o bus ao motor de agentes: inbound -> resposta -> outbound."""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from src.conexoes.bus import InboundMessage, MessageBus, OutboundMessage

Processador = Callable[[str, str], str]


def _processador_padrao() -> Processador:
    # Import tardio: evita carregar o motor (e Ollama) quando não há canais.
    from src.agentes.executor import SistemaAgentes

    sistema = SistemaAgentes()

    def processar(nome_agente: str, pergunta: str) -> str:
        return sistema.executar(nome_agente, pergunta)

    return processar


class Runtime:
    def __init__(self, bus: MessageBus, processar: Processador | None = None) -> None:
        self._bus = bus
        self._processar = processar or _processador_padrao()
        self.agente_padrao = "generalista"

    async def processar_uma(self, msg: InboundMessage) -> OutboundMessage:
        resposta = await asyncio.to_thread(self._processar, self.agente_padrao, msg.texto)
        out = OutboundMessage(texto=resposta, canal=msg.canal, chat_id=msg.chat_id)
        await self._bus.publicar_saida(out)
        return out

    async def rodar(self) -> None:
        while True:
            msg = await self._bus.proxima_entrada()
            await self.processar_uma(msg)
