"""
Ferramentas que executam ANTES do LLM (Nível 1).
O LLM só interpreta o resultado — não faz o cálculo.
"""

import re
import math
from datetime import datetime


def calcular(expressao: str) -> str | None:
    """Avalia expressões matemáticas simples."""
    expressao_limpa = expressao.strip()

    padrao_math = re.compile(
        r'^[\d\s\+\-\*\/\.\(\)\%\^]+$|'
        r'\b(sqrt|sin|cos|tan|log|pow|abs|round|pi|e)\b'
    )

    if not padrao_math.search(expressao_limpa):
        return None

    expressao_limpa = expressao_limpa.replace("^", "**")

    namespace = {
        "__builtins__": {},
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
        "tan": math.tan, "log": math.log, "pow": pow,
        "abs": abs, "round": round, "pi": math.pi, "e": math.e,
    }

    try:
        resultado = eval(expressao_limpa, namespace)
        return f"Resultado: {resultado}"
    except Exception:
        return None


def obter_data_hora() -> str:
    """Retorna data e hora atual formatada."""
    agora = datetime.now()
    return (
        f"Data: {agora.strftime('%d/%m/%Y')} "
        f"({agora.strftime('%A')})\n"
        f"Hora: {agora.strftime('%H:%M:%S')}"
    )


def verificar_ferramenta_data(texto: str) -> str | None:
    """Verifica se a pergunta é sobre data/hora."""
    palavras_data = [
        "que horas", "hora atual", "que dia", "data de hoje",
        "dia hoje", "data atual", "horário", "que data"
    ]
    texto_lower = texto.lower()
    for p in palavras_data:
        if p in texto_lower:
            return obter_data_hora()
    return None


def verificar_ferramenta_calculo(texto: str) -> str | None:
    """Verifica se a pergunta é um cálculo simples."""
    padrao = re.compile(
        r'(?:quanto é|calcule?|resultado de|compute)\s*(.+)',
        re.IGNORECASE
    )
    match = padrao.search(texto)
    if match:
        return calcular(match.group(1))

    if re.match(r'^[\d\s\+\-\*\/\.\(\)\%\^]+$', texto.strip()):
        return calcular(texto)

    return None


def executar_ferramentas(texto: str) -> str | None:
    """
    Tenta resolver com ferramentas ANTES de enviar ao LLM.
    Retorna None se nenhuma ferramenta se aplica.
    """
    resultado = verificar_ferramenta_data(texto)
    if resultado:
        return resultado

    resultado = verificar_ferramenta_calculo(texto)
    if resultado:
        return resultado

    return None
