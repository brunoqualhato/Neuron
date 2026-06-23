from unittest.mock import patch

from src.provedores.base import RespostaLLM


@patch("src.core.llm._provider")
def test_chamar_llm_retorna_dict_compativel(mock_provider):
    mock_provider.chat.return_value = RespostaLLM(
        resposta="ok", tempo_ms=12, tokens_entrada=5, tokens_saida=2
    )
    from src.core import llm
    out = llm.chamar_llm("m", "sys", [{"role": "user", "content": "oi"}], stream=False)
    assert out == {"resposta": "ok", "tempo_ms": 12, "tokens_entrada": 5, "tokens_saida": 2}


@patch("src.core.llm._provider")
def test_verificar_modelo_disponivel_delega(mock_provider):
    mock_provider.modelo_disponivel.return_value = True
    from src.core import llm
    assert llm.verificar_modelo_disponivel("qwen3:1.7b") is True
    mock_provider.modelo_disponivel.assert_called_once_with("qwen3:1.7b")


@patch("src.core.llm._provider")
def test_chamar_llm_repassa_tuning_ao_provider(mock_provider):
    """Reconciliacao PR#1 + PR#3: o tuning (num_ctx/keep_alive) chega no provider."""
    mock_provider.chat.return_value = RespostaLLM(resposta="ok")
    from src.core import llm
    llm.chamar_llm("m", "s", [{"role": "user", "content": "x"}],
                   stream=False, num_ctx=2048, keep_alive="5m")
    kwargs = mock_provider.chat.call_args.kwargs
    assert kwargs["num_ctx"] == 2048
    assert kwargs["keep_alive"] == "5m"


@patch("src.core.llm._provider")
def test_coordenador_usa_keep_alive_efemero(mock_provider):
    """Modelo auxiliar nao deve ficar residente: keep_alive efemero."""
    from src.core.config import KEEP_ALIVE_EFEMERO, NUM_CTX_AUXILIAR
    mock_provider.chat.return_value = RespostaLLM(resposta="programador")
    from src.core import llm
    llm.chamar_coordenador("escreva codigo", "m", "classifique")
    kwargs = mock_provider.chat.call_args.kwargs
    assert kwargs["keep_alive"] == KEEP_ALIVE_EFEMERO
    assert kwargs["num_ctx"] == NUM_CTX_AUXILIAR
