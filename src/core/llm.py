"""
Interface com o Ollama.
Gerencia chamadas ao LLM com controle de nível de performance.
"""

import time
import ollama
from rich.console import Console

console = Console()


def chamar_llm(
    modelo: str,
    system_prompt: str,
    mensagens: list[dict],
    stream: bool = True,
    max_tokens: int = 2048,
    temperatura: float = 0.7,
) -> dict:
    """
    Chama o Ollama com streaming.
    Retorna dict com {resposta, tempo_ms, tokens_entrada, tokens_saida}.
    """
    msgs = [{"role": "system", "content": system_prompt}]
    for m in mensagens:
        msgs.append({"role": m["role"], "content": m["content"]})

    inicio = time.time()
    resposta_completa = ""
    tokens_in = 0
    tokens_out = 0

    options = {
        "temperature": temperatura,
        "num_predict": max_tokens,
    }

    if stream:
        try:
            stream_response = ollama.chat(
                model=modelo,
                messages=msgs,
                stream=True,
                options=options,
            )
            for chunk in stream_response:
                texto = chunk["message"]["content"]
                resposta_completa += texto
                console.print(texto, end="", style="green")

                if "eval_count" in chunk:
                    tokens_out = chunk["eval_count"]
                if "prompt_eval_count" in chunk:
                    tokens_in = chunk["prompt_eval_count"]

            console.print()
        except Exception as e:
            resposta_completa = f"Erro ao chamar modelo {modelo}: {str(e)}"
            console.print(f"\n[red]{resposta_completa}[/red]")
    else:
        try:
            response = ollama.chat(model=modelo, messages=msgs, options=options)
            resposta_completa = response["message"]["content"]
            tokens_in = response.get("prompt_eval_count", 0)
            tokens_out = response.get("eval_count", 0)
        except Exception as e:
            resposta_completa = f"Erro ao chamar modelo {modelo}: {str(e)}"

    tempo_ms = int((time.time() - inicio) * 1000)

    return {
        "resposta": resposta_completa,
        "tempo_ms": tempo_ms,
        "tokens_entrada": tokens_in,
        "tokens_saida": tokens_out,
    }


def chamar_coordenador(pergunta: str, modelo: str, system_prompt: str) -> str:
    """
    Chama o coordenador para classificar a pergunta.
    Sem streaming — precisa da resposta completa.
    """
    try:
        response = ollama.chat(
            model=modelo,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": pergunta},
            ],
            options={"temperature": 0.1, "num_predict": 20},
        )
        return response["message"]["content"].strip().lower()
    except Exception as e:
        console.print(f"[red]Erro no coordenador: {e}[/red]")
        return "analista"


def resumir_conversa(modelo: str, mensagens: list[dict]) -> str:
    """Gera resumo compacto da conversa."""
    texto_conversa = "\n".join(
        f"{m['role']}: {m['content']}" for m in mensagens
    )

    try:
        response = ollama.chat(
            model=modelo,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Resuma a conversa abaixo em no máximo 2 frases. "
                        "Capture o objetivo principal do usuário e decisões tomadas."
                    ),
                },
                {"role": "user", "content": texto_conversa},
            ],
            options={"temperature": 0.3, "num_predict": 100},
        )
        return response["message"]["content"]
    except Exception:
        return ""


def verificar_modelo_disponivel(modelo: str) -> bool:
    """Verifica se o modelo está disponível localmente."""
    try:
        modelos = ollama.list()
        nomes = [m["name"] for m in modelos.get("models", [])]
        return modelo in nomes or f"{modelo}:latest" in nomes
    except Exception:
        return False
