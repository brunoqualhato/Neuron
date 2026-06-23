"""Garante que o cache so guarda respostas deterministicas (nivel 1), nunca
respostas conversacionais (nivel 2/3) que dependem do historico."""
from unittest.mock import MagicMock

from src.agentes.executor import SistemaAgentes
from src.memoria.cache import Cache
from src.memoria.sqlite import Memoria


def _sistema(tmp_path):
    mem = Memoria(arquivo=str(tmp_path / "m.db"))
    cache = Cache(arquivo=str(tmp_path / "c.json"))
    return SistemaAgentes(memoria=mem, cache=cache, semantica=MagicMock())


def test_nivel1_e_cacheado(tmp_path):
    s = _sistema(tmp_path)
    s._salvar("quanto e 2+2", "Resultado: 4", "generalista", nivel=1, inicio=0.0)
    assert s.cache.buscar("generalista:quanto e 2+2") is not None
    s.fechar()


def test_nivel2_nao_e_cacheado(tmp_path):
    s = _sistema(tmp_path)
    s._salvar("qual meu nome", "Seu nome e Nikolas", "generalista", nivel=2, inicio=0.0)
    assert s.cache.buscar("generalista:qual meu nome") is None
    s.fechar()


def test_nivel3_nao_e_cacheado(tmp_path):
    s = _sistema(tmp_path)
    s._salvar("explique X", "X e uma coisa", "generalista", nivel=3, inicio=0.0)
    assert s.cache.buscar("generalista:explique X") is None
    s.fechar()
