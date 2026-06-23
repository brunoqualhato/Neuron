import asyncio
import time

from src.conexoes.bus import InboundMessage, MessageBus, OutboundMessage, SenderInfo
from src.conexoes.runtime import Runtime


def test_processar_uma_gera_outbound():
    async def cenario():
        bus = MessageBus()
        recebidas = []

        async def coletor(m: OutboundMessage):
            recebidas.append(m)

        bus.assinar_saida(coletor)

        def processar(agente, pergunta):
            return f"eco: {pergunta}"

        rt = Runtime(bus, processar)
        msg = InboundMessage(
            texto="oi", sender=SenderInfo(id="u1"), canal="cli", chat_id="c1"
        )
        out = await rt.processar_uma(msg)
        return out, recebidas

    out, recebidas = asyncio.run(cenario())
    assert out.texto == "eco: oi"
    assert out.canal == "cli"
    assert out.chat_id == "c1"
    assert len(recebidas) == 1
    assert recebidas[0].texto == "eco: oi"


def test_runtime_sinaliza_typing_enquanto_processa():
    """Com manager, o Runtime mantem 'digitando...' durante o processamento."""
    async def cenario():
        bus = MessageBus()
        chamadas = []

        class FakeManager:
            async def sinalizar_typing(self, canal, chat_id):
                chamadas.append((canal, chat_id))

        def processar(agente, pergunta):
            time.sleep(0.05)  # da tempo do loop de typing rodar
            return "ok"

        rt = Runtime(bus, processar, manager=FakeManager())
        rt.typing_intervalo_s = 0.01
        await rt.processar_uma(
            InboundMessage(texto="oi", sender=SenderInfo(id="u1"),
                           canal="telegram", chat_id="c1")
        )
        return chamadas

    chamadas = asyncio.run(cenario())
    assert ("telegram", "c1") in chamadas
