"""
Testes da ferramenta de raciocínio estruturado de programação.

Cobre:
  - Inicialização e persistência do plano
  - Geração de perguntas CoT por tipo de arquivo
  - Validação determinística (sem LLM)
  - Ciclo completo: iniciar → registrar → verificar → retroceder → finalizar
  - Extração de assinaturas compactas
  - Serialização/deserialização JSON
"""

import ast
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Isolamento: redireciona RACIOCINIO_DB para diretório temporário
import src.ferramentas.raciocinio_codigo as rc


# ══════════════════════════════════════════════════════════════
# FIXTURES
# ══════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def isolamento_db(tmp_path):
    """Redireciona banco de dados para diretório temporário."""
    db_original = rc.RACIOCINIO_DB
    rc.RACIOCINIO_DB = tmp_path / "raciocinio_teste.json"
    yield
    rc.RACIOCINIO_DB = db_original


@pytest.fixture
def etapas_exemplo():
    return [
        {"descricao": "Criar modelos de dados", "arquivo": "models.py", "dependencias": []},
        {"descricao": "Implementar storage JSON", "arquivo": "storage.py", "dependencias": [1]},
        {"descricao": "Criar CLI interativa", "arquivo": "main.py", "dependencias": [1, 2]},
    ]


@pytest.fixture
def plano_ativo(etapas_exemplo):
    return rc.iniciar_raciocinio("sistema de tarefas CLI", etapas_exemplo)


@pytest.fixture
def codigo_python_valido():
    return """
import json
from pathlib import Path

class TarefaManager:
    def __init__(self, arquivo: str = "tarefas.json"):
        self.arquivo = Path(arquivo)
        self.tarefas: list[dict] = []

    def adicionar(self, titulo: str) -> dict:
        tarefa = {"id": len(self.tarefas) + 1, "titulo": titulo, "feita": False}
        self.tarefas.append(tarefa)
        return tarefa

    def listar(self) -> list[dict]:
        return self.tarefas

    def salvar(self) -> None:
        self.arquivo.write_text(json.dumps(self.tarefas, ensure_ascii=False))
""".strip()


@pytest.fixture
def codigo_com_stubs():
    return """
class Gerenciador:
    def adicionar(self, item):
        pass

    def remover(self, id):
        ...

    def listar(self):
        # TODO: implementar
        pass
""".strip()


# ══════════════════════════════════════════════════════════════
# TESTES: INICIALIZAÇÃO
# ══════════════════════════════════════════════════════════════


def test_iniciar_raciocinio_cria_etapas(etapas_exemplo):
    plano = rc.iniciar_raciocinio("projeto teste", etapas_exemplo)

    assert len(plano.etapas) == 3
    assert plano.etapas[0].numero == 1
    assert plano.etapas[1].arquivo == "storage.py"
    assert plano.etapas[2].dependencias == [1, 2]


def test_iniciar_raciocinio_persiste(etapas_exemplo, tmp_path):
    rc.iniciar_raciocinio("persistência", etapas_exemplo)
    assert rc.RACIOCINIO_DB.exists()


def test_iniciar_raciocinio_limita_max_etapas():
    muitas_etapas = [
        {"descricao": f"Etapa {i}", "arquivo": f"mod{i}.py", "dependencias": []}
        for i in range(20)  # mais que MAX_ETAPAS
    ]
    plano = rc.iniciar_raciocinio("projeto grande", muitas_etapas)
    assert len(plano.etapas) <= rc.MAX_ETAPAS


def test_existe_plano_ativo_true(plano_ativo):
    assert rc.existe_plano_ativo() is True


def test_existe_plano_ativo_false():
    assert rc.existe_plano_ativo() is False


# ══════════════════════════════════════════════════════════════
# TESTES: PERGUNTAS CoT
# ══════════════════════════════════════════════════════════════


def test_cot_python_pergunta_sobre_entradas():
    pergunta = rc._gerar_pergunta_cot("criar gerenciador", "models.py", "app de tarefas")
    assert "entrada" in pergunta.lower() or "recebe" in pergunta.lower()
    assert "retorna" in pergunta.lower() or "retornar" in pergunta.lower()


def test_cot_requirements_pergunta_sobre_libs():
    pergunta = rc._gerar_pergunta_cot("dependências", "requirements.txt", "app flask")
    assert "pacote" in pergunta.lower() or "librar" in pergunta.lower()
    assert "pip" in pergunta.lower() or "import" in pergunta.lower()


def test_cot_html_pergunta_sobre_dados_dinamicos():
    pergunta = rc._gerar_pergunta_cot("template lista", "index.html", "app web")
    assert "dados" in pergunta.lower() or "dinâmico" in pergunta.lower()


def test_cot_js_pergunta_sobre_eventos():
    pergunta = rc._gerar_pergunta_cot("formulário", "app.js", "spa")
    assert "evento" in pergunta.lower() or "dom" in pergunta.lower()


def test_cot_generico():
    pergunta = rc._gerar_pergunta_cot("arquivo config", "config.toml", "qualquer")
    assert len(pergunta) > 10


# ══════════════════════════════════════════════════════════════
# TESTES: VALIDAÇÃO DETERMINÍSTICA
# ══════════════════════════════════════════════════════════════


def test_validar_codigo_python_valido(codigo_python_valido):
    problemas = rc._validar_codigo(codigo_python_valido, "models.py")
    assert problemas == []


def test_validar_codigo_syntax_error():
    codigo_ruim = "def foo(\n    x\n    return x"  # parêntese não fechado
    problemas = rc._validar_codigo(codigo_ruim, "foo.py")
    assert any("SyntaxError" in p for p in problemas)


def test_validar_codigo_stubs(codigo_com_stubs):
    problemas = rc._validar_codigo(codigo_com_stubs, "manager.py")
    assert any("stub" in p.lower() or "incompleta" in p.lower() for p in problemas)


def test_validar_codigo_html_em_py():
    html = "<!DOCTYPE html><html><body>hello</body></html>"
    problemas = rc._validar_codigo(html, "views.py")
    assert any("HTML" in p for p in problemas)


def test_validar_codigo_python_em_requirements():
    codigo = "from flask import Flask\ndef create_app(): pass"
    problemas = rc._validar_codigo(codigo, "requirements.txt")
    assert any("pacote" in p.lower() or "python" in p.lower() for p in problemas)


def test_validar_codigo_vazio():
    problemas = rc._validar_codigo("", "main.py")
    assert len(problemas) > 0


def test_validar_codigo_degeneracao():
    codigo = "\n".join(["print('hello')" for _ in range(10)])
    problemas = rc._validar_codigo(codigo + "\n" + "def foo(): pass", "main.py")
    assert any("degeneração" in p.lower() or "repetição" in p.lower() for p in problemas)


# ══════════════════════════════════════════════════════════════
# TESTES: EXTRAÇÃO DE ASSINATURAS
# ══════════════════════════════════════════════════════════════


def test_extrair_assinatura_classe(codigo_python_valido):
    assinatura = rc._extrair_assinatura_compacta(codigo_python_valido, "models.py")
    assert "class TarefaManager" in assinatura
    assert "def adicionar" in assinatura
    assert "def listar" in assinatura
    # Não deve incluir o corpo das funções
    assert "self.tarefas.append" not in assinatura


def test_extrair_assinatura_imports(codigo_python_valido):
    assinatura = rc._extrair_assinatura_compacta(codigo_python_valido, "models.py")
    assert "import json" in assinatura


def test_extrair_assinatura_nao_python():
    css = "body { font-family: sans-serif; }\nh1 { color: red; }"
    assinatura = rc._extrair_assinatura_compacta(css, "style.css")
    assert "body" in assinatura  # Primeiras linhas


def test_extrair_assinatura_syntax_error():
    codigo_ruim = "class Foo\n  def bar: pass"
    assinatura = rc._extrair_assinatura_compacta(codigo_ruim, "bad.py")
    assert isinstance(assinatura, str)  # Não explode


# ══════════════════════════════════════════════════════════════
# TESTES: CICLO COMPLETO
# ══════════════════════════════════════════════════════════════


def test_obter_etapa_atual(plano_ativo):
    resultado = rc.obter_etapa_atual()
    assert resultado is not None
    assert resultado["etapa_numero"] == 1
    assert resultado["arquivo"] == "models.py"
    assert "contexto_llm" in resultado
    assert "RACIOCÍNIO" in resultado["contexto_llm"]


def test_obter_etapa_atual_sem_plano():
    resultado = rc.obter_etapa_atual()
    assert resultado is None


def test_contexto_llm_inclui_cot(plano_ativo):
    resultado = rc.obter_etapa_atual()
    assert resultado is not None
    contexto = resultado["contexto_llm"]
    # Deve ter a pergunta CoT
    assert "RACIOCÍNIO" in contexto
    assert "1." in contexto  # Perguntas numeradas


def test_registrar_resultado_sucesso(plano_ativo, codigo_python_valido):
    rc.obter_etapa_atual()  # Ativa etapa 1
    resultado = rc.registrar_resultado(1, codigo_python_valido, aprovado=True)

    assert resultado["sucesso"] is True
    assert resultado["proxima_etapa"] == 2
    assert resultado["problemas_encontrados"] == []


def test_registrar_resultado_com_problema(plano_ativo, codigo_com_stubs):
    rc.obter_etapa_atual()
    resultado = rc.registrar_resultado(1, codigo_com_stubs, aprovado=False, problemas=["stubs detectados"])

    assert resultado["sucesso"] is False
    assert len(resultado["problemas_encontrados"]) > 0


def test_registrar_resultado_valida_deterministicamente(plano_ativo):
    """Mesmo aprovado=True, validação detecta código inválido."""
    rc.obter_etapa_atual()
    codigo_invalido = "def foo(\n    return 1"  # SyntaxError
    resultado = rc.registrar_resultado(1, codigo_invalido, aprovado=True)

    assert resultado["sucesso"] is False
    assert any("SyntaxError" in p for p in resultado["problemas_encontrados"])


def test_ciclo_avanca_etapas(plano_ativo, codigo_python_valido):
    # Conclui etapa 1
    rc.obter_etapa_atual()
    rc.registrar_resultado(1, codigo_python_valido, aprovado=True)

    # Etapa 2 deve estar disponível
    proxima = rc.obter_etapa_atual()
    assert proxima is not None
    assert proxima["etapa_numero"] == 2


def test_contexto_etapa_2_inclui_dep_etapa_1(plano_ativo, codigo_python_valido):
    """Etapa 2 deve receber assinatura da etapa 1 como dependência."""
    rc.obter_etapa_atual()
    rc.registrar_resultado(1, codigo_python_valido, aprovado=True)

    etapa2 = rc.obter_etapa_atual()
    assert etapa2 is not None
    # Contexto deve mencionar a dependência (etapa 1)
    assert "etapa 1" in etapa2["contexto_llm"].lower() or "dep" in etapa2["contexto_llm"].lower()


# ══════════════════════════════════════════════════════════════
# TESTES: VERIFICAÇÃO
# ══════════════════════════════════════════════════════════════


def test_verificar_etapa_valida(plano_ativo, codigo_python_valido):
    resultado = rc.verificar_etapa(1, codigo_python_valido)
    assert resultado["valido"] is True
    assert resultado["problemas"] == []


def test_verificar_etapa_invalida(plano_ativo):
    resultado = rc.verificar_etapa(1, "def foo(")
    assert resultado["valido"] is False
    assert len(resultado["problemas"]) > 0
    assert "sugestao_cot" in resultado
    assert len(resultado["sugestao_cot"]) > 0  # Dá dica de como corrigir


def test_verificar_etapa_sem_plano():
    resultado = rc.verificar_etapa(1, "qualquer código")
    assert resultado["valido"] is False


# ══════════════════════════════════════════════════════════════
# TESTES: RETROCEDER
# ══════════════════════════════════════════════════════════════


def test_retroceder_etapa_concluida(plano_ativo, codigo_python_valido):
    rc.obter_etapa_atual()
    rc.registrar_resultado(1, codigo_python_valido, aprovado=True)

    # Retrocede etapa 1
    resultado = rc.retroceder(1)
    assert resultado["sucesso"] is True

    # Deve estar pendente novamente
    plano = rc._carregar_plano()
    assert plano.etapas[0].status == rc.StatusEtapa.PENDENTE
    assert plano.etapas[0].codigo_aceito == ""


def test_retroceder_preserva_historico(plano_ativo, codigo_python_valido):
    """Histórico de tentativas deve ser mantido após retroceder."""
    rc.obter_etapa_atual()
    rc.registrar_resultado(1, codigo_python_valido, aprovado=True)
    rc.retroceder(1)

    plano = rc._carregar_plano()
    # A tentativa anterior ainda deve existir no histórico
    assert len(plano.etapas[0].tentativas) >= 1


def test_retroceder_contexto_inclui_feedback(plano_ativo, codigo_python_valido):
    """Após retroceder, o contexto deve mencionar que foi retrocedido."""
    rc.obter_etapa_atual()
    rc.registrar_resultado(1, codigo_python_valido, aprovado=True)
    resultado = rc.retroceder(1)

    assert "contexto_llm" in resultado
    # O contexto deve mencionar a tentativa anterior com problema
    assert len(resultado["contexto_llm"]) > 0


# ══════════════════════════════════════════════════════════════
# TESTES: CONTEXTO COMPLETO
# ══════════════════════════════════════════════════════════════


def test_obter_contexto_completo(plano_ativo):
    contexto = rc.obter_contexto_completo()
    assert "problema" in contexto
    assert "etapas" in contexto
    assert len(contexto["etapas"]) == 3
    assert contexto["etapas"][0]["numero"] == 1


def test_obter_contexto_sem_plano():
    resultado = rc.obter_contexto_completo()
    assert "erro" in resultado


def test_progresso_atualiza(plano_ativo, codigo_python_valido):
    rc.obter_etapa_atual()
    rc.registrar_resultado(1, codigo_python_valido, aprovado=True)

    contexto = rc.obter_contexto_completo()
    assert contexto["progresso"] == "1/3"


# ══════════════════════════════════════════════════════════════
# TESTES: FINALIZAÇÃO
# ══════════════════════════════════════════════════════════════


def test_finalizar_retorna_sumario(plano_ativo):
    sumario = rc.finalizar_raciocinio()
    assert "problema" in sumario
    assert "etapas_concluidas" in sumario
    assert "tempo_s" in sumario
    assert "arquivos_gerados" in sumario


def test_finalizar_limpa_persistencia(plano_ativo):
    rc.finalizar_raciocinio()
    assert not rc.RACIOCINIO_DB.exists()


def test_finalizar_sem_plano():
    resultado = rc.finalizar_raciocinio()
    assert "erro" in resultado


# ══════════════════════════════════════════════════════════════
# TESTES: SERIALIZAÇÃO
# ══════════════════════════════════════════════════════════════


def test_persistencia_roundtrip(plano_ativo, codigo_python_valido):
    """Dados salvos devem ser idênticos aos carregados."""
    rc.obter_etapa_atual()
    rc.registrar_resultado(1, codigo_python_valido, aprovado=True)

    plano_recarregado = rc._carregar_plano()
    assert plano_recarregado is not None
    assert plano_recarregado.etapas[0].status == rc.StatusEtapa.CONCLUIDA
    assert plano_recarregado.etapas[0].codigo_aceito == codigo_python_valido


def test_carregar_plano_arquivo_corrompido(tmp_path):
    rc.RACIOCINIO_DB = tmp_path / "corrompido.json"
    rc.RACIOCINIO_DB.write_text("{ json inválido !!!", encoding="utf-8")
    plano = rc._carregar_plano()
    assert plano is None  # Não deve explodir


def test_salvar_limita_historico_tentativas(plano_ativo):
    """Não deve salvar mais que MAX_HISTORICO_ETAPA tentativas."""
    rc.obter_etapa_atual()

    # Faz muitas tentativas fracassadas
    codigo_ruim = "def foo(:"  # SyntaxError sempre
    for _ in range(rc.MAX_HISTORICO_ETAPA + 3):
        rc.registrar_resultado(1, codigo_ruim, aprovado=False)

    plano = rc._carregar_plano()
    assert len(plano.etapas[0].tentativas) <= rc.MAX_HISTORICO_ETAPA
