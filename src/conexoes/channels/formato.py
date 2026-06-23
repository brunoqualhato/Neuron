"""Conversao de Markdown para HTML seguro do Telegram.

Portado do nanobot (`nanobot/channels/telegram.py::_markdown_to_telegram_html`).

Por que existe: modelos locais pequenos (gemma2:2b etc.) respondem em Markdown
padrao (`**negrito**`, listas com `-`, ` ```bloco``` `). O Telegram NAO renderiza
esse Markdown no modo default, entao o texto chega cru no chat. Convertendo para
HTML e enviando com `parse_mode="HTML"` o texto fica formatado, e o HTML so exige
escapar tres caracteres (`&`, `<`, `>`), bem mais simples que o MarkdownV2.
"""
from __future__ import annotations

import re


def markdown_para_telegram_html(texto: str) -> str:
    """Converte Markdown comum em HTML aceito pelo parse_mode HTML do Telegram."""
    if not texto:
        return ""

    # 1. Extrai e protege blocos de codigo (nao processar o conteudo interno).
    blocos_codigo: list[str] = []

    def _guardar_bloco(m: re.Match) -> str:
        blocos_codigo.append(m.group(1))
        return f"\x00CB{len(blocos_codigo) - 1}\x00"

    texto = re.sub(r"```[\w]*\n?([\s\S]*?)```", _guardar_bloco, texto)

    # 2. Extrai e protege codigo inline.
    codigos_inline: list[str] = []

    def _guardar_inline(m: re.Match) -> str:
        codigos_inline.append(m.group(1))
        return f"\x00IC{len(codigos_inline) - 1}\x00"

    texto = re.sub(r"`([^`]+)`", _guardar_inline, texto)

    # 3. Cabecalhos "# Titulo" -> apenas o texto do titulo.
    texto = re.sub(r"^#{1,6}\s+(.+)$", r"\1", texto, flags=re.MULTILINE)

    # 4. Citacoes "> texto" -> so o texto (antes de escapar o HTML).
    texto = re.sub(r"^>\s*(.*)$", r"\1", texto, flags=re.MULTILINE)

    # 5. Escapa os caracteres especiais de HTML.
    texto = texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Links [texto](url) - antes de negrito/italico para tratar aninhamento.
    texto = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', texto)

    # 7. Negrito **texto** ou __texto__.
    texto = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", texto)
    texto = re.sub(r"__(.+?)__", r"<b>\1</b>", texto)

    # 8. Italico _texto_ (evita casar dentro de palavras como some_var_name).
    texto = re.sub(r"(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])", r"<i>\1</i>", texto)

    # 9. Tachado ~~texto~~.
    texto = re.sub(r"~~(.+?)~~", r"<s>\1</s>", texto)

    # 10. Listas "- item" / "* item" -> "• item".
    texto = re.sub(r"^[-*]\s+", "• ", texto, flags=re.MULTILINE)

    # 11. Restaura codigo inline com tags HTML (escapando o conteudo).
    for i, codigo in enumerate(codigos_inline):
        escapado = codigo.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        texto = texto.replace(f"\x00IC{i}\x00", f"<code>{escapado}</code>")

    # 12. Restaura blocos de codigo com tags HTML (escapando o conteudo).
    #     .strip() remove a quebra de linha antes do fechamento ``` (melhoria
    #     sobre o nanobot: evita linha em branco sobrando dentro do <pre>).
    for i, codigo in enumerate(blocos_codigo):
        limpo = codigo.strip()
        escapado = limpo.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        texto = texto.replace(f"\x00CB{i}\x00", f"<pre><code>{escapado}</code></pre>")

    return texto
