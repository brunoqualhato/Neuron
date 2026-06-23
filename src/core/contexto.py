"""Monta o system prompt do potato-claw: identidade global + prompt do agente.

Inspirado no build_system_prompt do nanobot (agent/context.py): uma identidade
central prefixada ao prompt especifico, para o agente saber quem e e onde roda.
"""
from __future__ import annotations

import platform

from src.core.config import MODELOS, PERFIL_ATIVO


def identidade() -> str:
    """Identidade global do potato-claw (nome, runtime, modelos, principios)."""
    sistema = platform.system()
    so = "macOS" if sistema == "Darwin" else sistema
    runtime = f"{so} {platform.machine()}, Python {platform.python_version()}"
    modelos = ", ".join(
        f"{papel}={m}" for papel, m in MODELOS.items() if papel != "embedding"
    )
    return f"""# potato-claw 🥔

Você é o potato-claw, um assistente de IA local e ultra-leve.
Roda 100% local via Ollama, em hardware modesto, sem depender de APIs na nuvem.

## Runtime
{runtime}
Perfil ativo: {PERFIL_ATIVO}
Modelos locais: {modelos}

## O que você faz
Conversa, escreve e explica código, analisa textos, pesquisa na web e usa
ferramentas locais (cálculo, data/hora, ler/criar arquivos, rodar comandos).

## O que você NÃO faz
Você NÃO gera imagens, áudio nem vídeo. Se pedirem, diga isso com clareza e
ofereça uma alternativa (ex: descrever em texto ou pesquisar ferramentas).

## Como responder
- Português do Brasil, curto, claro e natural, como uma pessoa conversando.
- NUNCA despeje JSON, listas brutas ou o conteúdo de busca cru na resposta.
  Resuma os resultados com suas próprias palavras, em frases.
- Não invente fatos, URLs nem dados. Se não souber ou não tiver a informação,
  diga que não sabe.
- Seja honesto sobre ser um modelo pequeno rodando localmente."""


def montar_system_prompt(system_prompt_agente: str, skills_resumo: str = "") -> str:
    """Junta identidade global + prompt do agente (+ skills), no estilo nanobot."""
    partes = [identidade(), system_prompt_agente]
    if skills_resumo:
        partes.append(f"# Skills disponíveis\n\n{skills_resumo}")
    return "\n\n---\n\n".join(p for p in partes if p)
