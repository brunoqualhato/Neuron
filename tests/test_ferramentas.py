"""Testes para as ferramentas de execução pré-LLM."""

import pytest

from src.ferramentas.resolver import (
    calcular,
    executar_comando_local,
    executar_ferramentas,
    verificar_ferramenta_calculo,
    verificar_ferramenta_data,
    verificar_ferramenta_saudacao,
)


class TestCalcular:
    @pytest.mark.parametrize("expr,esperado", [
        ("2 + 2", 4),
        ("10 * 3", 30),
        ("100 / 4", 25.0),
        ("2 ** 10", 1024),
        ("sqrt(16)", 4.0),
        ("pi", 3.141592653589793),
    ])
    def test_calculos_validos(self, expr, esperado):
        resultado = calcular(expr)
        assert resultado is not None
        assert str(esperado) in resultado

    @pytest.mark.parametrize("expr", [
        "hello world",
        "como vai",
        "import os",
    ])
    def test_nao_matematico_retorna_none(self, expr):
        assert calcular(expr) is None

    def test_expressao_invalida(self):
        # Divisão por zero retorna None (exception)
        resultado = calcular("1/0")
        assert resultado is None


class TestVerificarFerramentaData:
    @pytest.mark.parametrize("entrada", [
        "que horas são",
        "hora atual",
        "que dia é hoje",
        "data de hoje",
    ])
    def test_detecta_pergunta_data(self, entrada):
        resultado = verificar_ferramenta_data(entrada)
        assert resultado is not None
        assert "Data:" in resultado or "Hora:" in resultado

    def test_nao_detecta_outro_texto(self):
        assert verificar_ferramenta_data("como programar em python") is None


class TestVerificarFerramentaCalculo:
    def test_quanto_e(self):
        resultado = verificar_ferramenta_calculo("quanto é 5 + 5")
        assert resultado is not None
        assert "10" in resultado

    def test_calcule(self):
        resultado = verificar_ferramenta_calculo("calcule 100 * 2")
        assert resultado is not None
        assert "200" in resultado

    def test_expressao_pura(self):
        resultado = verificar_ferramenta_calculo("3 + 7")
        assert resultado is not None
        assert "10" in resultado

    def test_texto_normal_retorna_none(self):
        assert verificar_ferramenta_calculo("o que é python") is None


class TestVerificarFerramentaSaudacao:
    @pytest.mark.parametrize("entrada", [
        "oi", "olá", "bom dia", "boa tarde", "hello",
    ])
    def test_saudacoes(self, entrada):
        resultado = verificar_ferramenta_saudacao(entrada)
        assert resultado is not None
        assert "pronto" in resultado.lower() or "Olá" in resultado

    def test_nao_saudacao(self):
        assert verificar_ferramenta_saudacao("crie um script python") is None


class TestExecutarFerramentas:
    def test_data_hora(self):
        resultado = executar_ferramentas("que horas são")
        assert resultado is not None

    def test_calculo(self):
        resultado = executar_ferramentas("quanto é 2 + 2")
        assert resultado is not None
        assert "4" in resultado

    def test_saudacao(self):
        resultado = executar_ferramentas("oi")
        assert resultado is not None

    def test_sem_ferramenta_retorna_none(self):
        resultado = executar_ferramentas("explique o teorema de pitágoras detalhadamente")
        assert resultado is None


class TestExecutarComandoLocal:
    """Hardening da allowlist de execução de comandos locais."""

    def test_comando_permitido_executa(self):
        resultado = executar_comando_local("echo oi")
        assert "oi" in resultado
        assert "Exit code: 0" in resultado

    def test_binario_fora_da_allowlist_bloqueado(self):
        resultado = executar_comando_local("rm arquivo.txt")
        assert "não está na lista de permitidos" in resultado

    def test_binario_com_caminho_absoluto_bloqueado(self):
        # '/tmp/cat' não pode passar como 'cat' e executar o binário do caminho.
        resultado = executar_comando_local("/tmp/cat segredo.txt")
        assert "sem caminho" in resultado

    def test_node_eval_bloqueado(self):
        resultado = executar_comando_local('node -e "process.exit(1)"')
        assert "bloqueada por segurança" in resultado

    def test_node_print_bloqueado(self):
        resultado = executar_comando_local("node --eval=1")
        assert "bloqueada por segurança" in resultado

    def test_find_exec_bloqueado(self):
        resultado = executar_comando_local("find . -name x -exec echo {} ;")
        assert "bloqueada por segurança" in resultado

    def test_find_delete_bloqueado(self):
        resultado = executar_comando_local("find . -delete")
        assert "bloqueada por segurança" in resultado

    def test_sed_in_place_bloqueado(self):
        resultado = executar_comando_local("sed -i s/a/b/ arquivo.txt")
        assert "bloqueada por segurança" in resultado

    def test_git_clone_bloqueado(self):
        resultado = executar_comando_local("git clone https://exemplo.com/repo")
        assert "bloqueado por segurança" in resultado

    def test_git_clone_apos_opcao_global_bloqueado(self):
        # subcomando após opção global não pode contornar a blocklist.
        resultado = executar_comando_local("git -c core.pager=cat clone https://x/y")
        assert "bloqueado por segurança" in resultado

    def test_git_status_permitido(self):
        # subcomando de leitura continua passando pela allowlist (executa de fato).
        resultado = executar_comando_local("git status")
        assert "Exit code" in resultado

    def test_argumento_caminho_absoluto_bloqueado(self):
        resultado = executar_comando_local("cat /etc/passwd")
        assert "fora do projeto" in resultado

    def test_argumento_caminho_em_flag_bloqueado(self):
        # caminho absoluto embutido em flag (--file=/...) também é bloqueado.
        resultado = executar_comando_local("grep --file=/etc/passwd x")
        assert "fora do projeto" in resultado

    def test_argumento_caminho_windows_bloqueado(self):
        # unidade Windows com barra normal (sobrevive ao shlex POSIX).
        resultado = executar_comando_local("cat C:/Windows/system32/drivers/etc/hosts")
        assert "fora do projeto" in resultado

    def test_argumento_traversal_bloqueado(self):
        resultado = executar_comando_local("cat ../../etc/passwd")
        assert "fora do projeto" in resultado

    def test_argumento_home_bloqueado(self):
        resultado = executar_comando_local("cat ~/.ssh/id_rsa")
        assert "fora do projeto" in resultado

    def test_flag_destrutiva_bloqueada(self):
        resultado = executar_comando_local("git checkout --force main")
        assert "destrutivas" in resultado

    def test_argumento_relativo_no_projeto_permitido(self):
        # caminho relativo dentro do projeto não é bloqueado pelas guardas.
        resultado = executar_comando_local("ls src")
        assert "não está na lista" not in resultado
        assert "fora do projeto" not in resultado
