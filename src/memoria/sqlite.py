"""
Camada 3 de memória: SQLite.
Histórico, resumos, contexto persistente e métricas.
"""

import logging
import sqlite3
from datetime import datetime

from src.core.config import MEMORIA_ARQUIVO

logger = logging.getLogger(__name__)


class Memoria:
    """Memória persistente com SQLite."""

    def __init__(self, arquivo: str = MEMORIA_ARQUIVO):
        self.conn = sqlite3.connect(arquivo)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._criar_tabelas()

    def _criar_tabelas(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS resumos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                resumo TEXT NOT NULL,
                criado_em TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contexto (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL,
                atualizado_em TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS historico (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                papel TEXT NOT NULL,
                conteudo TEXT NOT NULL,
                agente TEXT,
                nivel INTEGER DEFAULT 0,
                criado_em TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metricas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agente TEXT,
                nivel INTEGER,
                tempo_ms INTEGER,
                tokens_entrada INTEGER DEFAULT 0,
                tokens_saida INTEGER DEFAULT 0,
                fonte TEXT,
                criado_em TEXT NOT NULL
            );
        """)
        self.conn.commit()

    def salvar_mensagem(self, papel: str, conteudo: str, agente: str | None = None, nivel: int = 0):
        self.conn.execute(
            "INSERT INTO historico (papel, conteudo, agente, nivel, criado_em) VALUES (?, ?, ?, ?, ?)",
            (papel, conteudo, agente, nivel, datetime.now().isoformat()),
        )
        self.conn.commit()

    def ultimas_mensagens(self, n: int = 3) -> list[dict]:
        cursor = self.conn.execute(
            "SELECT papel, conteudo, agente FROM historico ORDER BY id DESC LIMIT ?",
            (n,),
        )
        rows = cursor.fetchall()
        return [
            {"role": r[0], "content": r[1], "agente": r[2]}
            for r in reversed(rows)
        ]

    def salvar_resumo(self, resumo: str):
        self.conn.execute(
            "INSERT INTO resumos (resumo, criado_em) VALUES (?, ?)",
            (resumo, datetime.now().isoformat()),
        )
        self.conn.commit()

    def ultimo_resumo(self) -> str | None:
        cursor = self.conn.execute(
            "SELECT resumo FROM resumos ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def definir_contexto(self, chave: str, valor: str):
        self.conn.execute(
            """INSERT OR REPLACE INTO contexto (chave, valor, atualizado_em)
               VALUES (?, ?, ?)""",
            (chave, valor, datetime.now().isoformat()),
        )
        self.conn.commit()

    def obter_contexto(self, chave: str) -> str | None:
        cursor = self.conn.execute(
            "SELECT valor FROM contexto WHERE chave = ?", (chave,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def total_mensagens(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) FROM historico")
        return cursor.fetchone()[0]

    def salvar_metrica(self, agente: str, nivel: int, tempo_ms: int,
                       tokens_entrada: int = 0, tokens_saida: int = 0, fonte: str = ""):
        self.conn.execute(
            """INSERT INTO metricas (agente, nivel, tempo_ms, tokens_entrada, tokens_saida, fonte, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (agente, nivel, tempo_ms, tokens_entrada, tokens_saida, fonte, datetime.now().isoformat()),
        )
        self.conn.commit()

    def metricas_resumo(self) -> dict:
        cursor = self.conn.execute("""
            SELECT nivel, COUNT(*) as total, AVG(tempo_ms) as avg_ms
            FROM metricas GROUP BY nivel ORDER BY nivel
        """)
        return {
            row[0]: {"total": row[1], "avg_ms": round(row[2], 1)}
            for row in cursor.fetchall()
        }

    def limpar_historico(self):
        self.conn.execute("DELETE FROM historico")
        self.conn.commit()

    def fechar(self):
        self.conn.close()
