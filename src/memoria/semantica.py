"""
Camada 2 de memória: Memória Semântica (ChromaDB).
Busca por similaridade vetorial usando embeddings locais.
"""

import hashlib
from datetime import datetime

import chromadb
import ollama as ollama_client

from src.core.config import (
    CHROMADB_DIR, CHROMADB_COLLECTION, CHROMADB_TOP_K,
    CHROMADB_THRESHOLD, EMBEDDING_MODEL,
)


class MemoriaSemantica:
    """
    Memória vetorial com ChromaDB.
    Armazena pares pergunta+resposta e busca por similaridade.
    Usa embeddings locais do Ollama (nomic-embed-text).
    """

    def __init__(self):
        self.client = chromadb.PersistentClient(path=CHROMADB_DIR)
        self.collection = self.client.get_or_create_collection(
            name=CHROMADB_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._embedding_disponivel = None

    def _verificar_embedding(self) -> bool:
        """Verifica se o modelo de embedding está disponível."""
        if self._embedding_disponivel is not None:
            return self._embedding_disponivel
        try:
            ollama_client.embeddings(model=EMBEDDING_MODEL, prompt="teste")
            self._embedding_disponivel = True
        except Exception:
            self._embedding_disponivel = False
        return self._embedding_disponivel

    def _gerar_embedding(self, texto: str) -> list[float]:
        """Gera embedding usando Ollama."""
        response = ollama_client.embeddings(model=EMBEDDING_MODEL, prompt=texto)
        return response["embedding"]

    def buscar_similar(self, pergunta: str, top_k: int = CHROMADB_TOP_K) -> list[dict]:
        """
        Busca documentos similares.
        Retorna lista de {conteudo, similaridade, metadata}.
        """
        if not self._verificar_embedding():
            return []

        if self.collection.count() == 0:
            return []

        try:
            embedding = self._gerar_embedding(pergunta)
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=min(top_k, self.collection.count()),
                include=["documents", "metadatas", "distances"],
            )

            documentos = []
            for i, doc in enumerate(results["documents"][0]):
                distancia = results["distances"][0][i]
                similaridade = 1 - (distancia / 2)

                if similaridade >= CHROMADB_THRESHOLD:
                    documentos.append({
                        "conteudo": doc,
                        "similaridade": similaridade,
                        "metadata": results["metadatas"][0][i],
                    })

            return documentos

        except Exception:
            return []

    def adicionar(self, pergunta: str, resposta: str, agente: str = "", metadata: dict = None):
        """Adiciona par pergunta+resposta ao ChromaDB."""
        if not self._verificar_embedding():
            return

        try:
            documento = f"Pergunta: {pergunta}\nResposta: {resposta}"
            embedding = self._gerar_embedding(pergunta)

            meta = {
                "agente": agente,
                "tipo": "conversa",
                "criado_em": datetime.now().isoformat(),
            }
            if metadata:
                meta.update(metadata)

            doc_id = hashlib.sha256(
                f"{pergunta}:{datetime.now().isoformat()}".encode()
            ).hexdigest()[:16]

            self.collection.add(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[documento],
                metadatas=[meta],
            )
        except Exception:
            pass

    def adicionar_conhecimento(self, texto: str, fonte: str = "", tipo: str = "conhecimento"):
        """Adiciona conhecimento avulso (docs, notas, etc)."""
        if not self._verificar_embedding():
            return

        try:
            embedding = self._gerar_embedding(texto)
            doc_id = hashlib.sha256(texto[:100].encode()).hexdigest()[:16]

            self.collection.add(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[texto],
                metadatas=[{
                    "tipo": tipo,
                    "fonte": fonte,
                    "criado_em": datetime.now().isoformat(),
                }],
            )
        except Exception:
            pass

    def total_documentos(self) -> int:
        return self.collection.count()

    def estatisticas(self) -> dict:
        return {
            "documentos": self.total_documentos(),
            "embedding_model": EMBEDDING_MODEL,
            "disponivel": self._verificar_embedding(),
        }
