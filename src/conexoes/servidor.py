"""Servidor de canais: sobe os canais configurados e roda o agente continuamente.

Modo "sempre no ar" do potato-claw (estilo nanobot). Offline-first: sem canal
configurado (nenhuma env), nao sobe nada e avisa.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from rich.console import Console

from src.conexoes.bus import MessageBus
from src.conexoes.channels import registry as canais_registry
from src.conexoes.channels.manager import ChannelManager
from src.conexoes.runtime import Runtime
from src.core.config import canais_configurados

console = Console()


def montar_servidor(
    bus: MessageBus | None = None,
    processar: Callable[[str, str], str] | None = None,
) -> tuple[ChannelManager, Runtime, list]:
    """Monta bus + manager + canais configurados + runtime (nao roda ainda)."""
    bus = bus or MessageBus()
    mgr = ChannelManager(bus)
    canais = []
    for cfg in canais_configurados():
        canal = canais_registry.criar(cfg["tipo"], bus, cfg)
        mgr.adicionar(canal)
        canais.append(canal)
    rt = Runtime(bus, processar, manager=mgr)
    return mgr, rt, canais


async def servir(processar: Callable[[str, str], str] | None = None) -> None:
    """Sobe os canais configurados e roda ate ser interrompido (Ctrl+C)."""
    if not canais_configurados():
        console.print(
            "[yellow]Nenhum canal configurado.[/yellow] "
            "Defina TELEGRAM_BOT_TOKEN para ligar o Telegram. "
            "Sem canais, use o modo interativo: python main.py"
        )
        return

    mgr, rt, canais = montar_servidor(processar=processar)
    nomes = ", ".join(c.nome for c in canais)
    console.print(f"[green]🥔 potato-claw no ar[/green] - canais: {nomes}. Ctrl+C para parar.")

    tarefas = {
        asyncio.create_task(rt.rodar(), name="runtime"),
        *(
            asyncio.create_task(c.start(), name=f"canal:{c.nome}")
            for c in canais
        ),
    }
    try:
        concluidas, _ = await asyncio.wait(
            tarefas, return_when=asyncio.FIRST_COMPLETED
        )
        # Um canal que encerra (por exemplo, token fatal do Telegram) torna o
        # servidor incapaz de receber mensagens. Encerra o restante da stack,
        # propagando exceções reais para o supervisor reiniciar o processo.
        for tarefa in concluidas:
            erro = tarefa.exception()
            if erro is not None:
                raise erro
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        for tarefa in tarefas:
            if not tarefa.done():
                tarefa.cancel()
        await asyncio.gather(*tarefas, return_exceptions=True)
        await mgr.parar_todos()
