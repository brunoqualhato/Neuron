"""Testes do conversor Markdown -> HTML seguro do Telegram (porte do nanobot)."""
from src.conexoes.channels.formato import markdown_para_telegram_html


def test_vazio_vira_string_vazia():
    assert markdown_para_telegram_html("") == ""


def test_negrito_asteriscos():
    assert markdown_para_telegram_html("isto e **importante**") == "isto e <b>importante</b>"


def test_negrito_underscores():
    assert markdown_para_telegram_html("__forte__") == "<b>forte</b>"


def test_italico():
    assert markdown_para_telegram_html("um _detalhe_ aqui") == "um <i>detalhe</i> aqui"


def test_italico_nao_quebra_nome_com_underscore():
    # some_var_name nao deve virar italico
    assert markdown_para_telegram_html("a variavel some_var_name") == "a variavel some_var_name"


def test_tachado():
    assert markdown_para_telegram_html("~~errado~~") == "<s>errado</s>"


def test_lista_com_traco_vira_bullet():
    assert markdown_para_telegram_html("- item um\n- item dois") == "• item um\n• item dois"


def test_lista_com_asterisco_vira_bullet():
    assert markdown_para_telegram_html("* primeiro\n* segundo") == "• primeiro\n• segundo"


def test_cabecalho_vira_texto_simples():
    assert markdown_para_telegram_html("## Titulo") == "Titulo"


def test_citacao_vira_texto():
    assert markdown_para_telegram_html("> citado") == "citado"


def test_link():
    esperado = '<a href="https://x.com">site</a>'
    assert markdown_para_telegram_html("[site](https://x.com)") == esperado


def test_escapa_caracteres_html():
    # < > & crus precisam ser escapados para o parse_mode HTML nao quebrar
    assert markdown_para_telegram_html("2 < 3 & 4 > 1") == "2 &lt; 3 &amp; 4 &gt; 1"


def test_codigo_inline():
    assert markdown_para_telegram_html("rode `ls -la` agora") == "rode <code>ls -la</code> agora"


def test_codigo_inline_preserva_simbolos_e_escapa():
    assert markdown_para_telegram_html("`a < b`") == "<code>a &lt; b</code>"


def test_bloco_de_codigo():
    entrada = "```python\nprint(1)\n```"
    assert markdown_para_telegram_html(entrada) == "<pre><code>print(1)</code></pre>"


def test_markdown_dentro_de_codigo_nao_e_convertido():
    # **isto** dentro de code deve ficar literal
    assert markdown_para_telegram_html("`**x**`") == "<code>**x**</code>"
