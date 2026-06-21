"""
Camada 1 de memória: Cache exato (JSON).
Hash da pergunta → resposta instantânea.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime

from src.core.config import CACHE_ARQUIVO, CACHE_HABILITADO


class Cache:
    """Cache de respostas para evitar chamadas repetidas ao LLM."""

    def __init__(self, arquivo: str = CACHE_ARQUIVO):
        self.arquivo = Path(arquivo)
        self.dados: dict[str, dict] = {}
        self._carregar()

    def _carregar(self):
        if self.arquivo.exists():
            try:
                self.dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                self.dados = {}

    def _salvar(self):
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo.write_text(
            json.dumps(self.dados, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _hash(texto: str) -> str:
        return hashlib.sha256(texto.strip().lower().encode()).hexdigest()[:16]

    @staticmethod
    def _consulta_base(pergunta: str) -> str:
        """Extrai a pergunta sem prefixo de agente quando existir."""
        if ":" in pergunta:
            return pergunta.split(":", 1)[1].strip().lower()
        return pergunta.strip().lower()

    @classmethod
    def _nao_cachear_consulta(cls, pergunta: str) -> bool:
        """Evita cache para entradas genéricas que causam respostas fora de contexto."""
        base = cls._consulta_base(pergunta)
        if not base:
            return True

        tokens = base.split()
        if len(tokens) <= 2:
            genericas = {
                "oi", "olá", "ola", "hello", "hey", "e ai", "e aí",
                "ok", "blz", "valeu", "obrigado", "obg", "sim", "não", "nao",
            }
            if base in genericas:
                return True

        return False

    def buscar(self, pergunta: str) -> str | None:
        if not CACHE_HABILITADO:
            return None
        if self._nao_cachear_consulta(pergunta):
            return None
        chave = self._hash(pergunta)
        entry = self.dados.get(chave)
        if entry:
            entry["hits"] = entry.get("hits", 0) + 1
            entry["ultimo_uso"] = datetime.now().isoformat()
            self._salvar()
            return entry["resposta"]
        return None

    def salvar(self, pergunta: str, resposta: str, agente: str = ""):
        if not CACHE_HABILITADO:
            return
        if self._nao_cachear_consulta(pergunta):
            return
        chave = self._hash(pergunta)
        self.dados[chave] = {
            "resposta": resposta,
            "agente": agente,
            "hits": 1,
            "criado_em": datetime.now().isoformat(),
            "ultimo_uso": datetime.now().isoformat(),
        }
        self._salvar()

    def limpar(self):
        self.dados = {}
        self._salvar()

    def estatisticas(self) -> dict:
        total = len(self.dados)
        hits_total = sum(e.get("hits", 0) for e in self.dados.values())
        return {"entradas": total, "hits_total": hits_total}
