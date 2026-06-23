from src.core import contexto
from src.core.config import MODELOS


def test_identidade_inclui_nome_e_modelo_ativo():
    ident = contexto.identidade()
    assert "potato-claw" in ident
    assert MODELOS["rapido"] in ident  # o modelo ativo aparece (resolve "qual modelo usa")
    assert "local" in ident.lower()


def test_montar_system_prompt_prefixa_identidade():
    prompt = contexto.montar_system_prompt("Voce e um programador.")
    assert "potato-claw" in prompt
    assert "Voce e um programador." in prompt
    assert prompt.index("potato-claw") < prompt.index("Voce e um programador.")


def test_montar_system_prompt_inclui_skills_quando_passado():
    prompt = contexto.montar_system_prompt("base", skills_resumo="- eco: repete")
    assert "Skills" in prompt
    assert "eco: repete" in prompt


def test_montar_system_prompt_sem_skills_nao_tem_secao():
    prompt = contexto.montar_system_prompt("base")
    assert "Skills disponíveis" not in prompt
