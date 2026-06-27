"""
Ferramenta de Raciocínio Estruturado para Programação.

Mantém etapas de um problema de código em memória persistente (SQLite)
para que os agentes possam navegar, corrigir e verificar cada passo
de forma iterativa — sem refazer o raciocínio inteiro a cada turno.

Fluxo de uso:
  1. iniciar_raciocinio(problema) → cria plano de etapas via CoT compacto
  2. obter_etapa_atual()          → retorna contexto da etapa pendente
  3. registrar_resultado(etapa, codigo, ok) → avança ou regride
  4. verificar_etapa(etapa, codigo)         → valida sintaxe + semântica
  5. retroceder(etapa)                      → desfaz e re-executa
  6. finalizar()                            → limpa e retorna sumário

Todas as operações são baratas (SQLite, AST, heurísticas) — sem chamar LLM.
O LLM apenas preenche o conteúdo das etapas; esta ferramenta gerencia o estado.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from src.core.config import DATA_DIR

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════════════

RACIOCINIO_DB = DATA_DIR / "raciocinio_codigo.json"
MAX_ETAPAS = 12
MAX_HISTORICO_ETAPA = 5  # Tentativas salvas por etapa

# Heurísticas de qualidade de código (sem gastar tokens do LLM)
SINAIS_STUB = {"pass", "...", "TODO", "FIXME", "NotImplemented"}
MIN_CHARS_CODIGO_VALIDO = 10


# ══════════════════════════════════════════════════════════════
# TIPOS
# ══════════════════════════════════════════════════════════════


class StatusEtapa(str, Enum):
    PENDENTE = "pendente"
    EM_PROGRESSO = "em_progresso"
    CONCLUIDA = "concluida"
    COM_PROBLEMA = "com_problema"
    PULADA = "pulada"


@dataclass
class TentativaEtapa:
    """Snapshot de uma tentativa de implementação de uma etapa."""
    codigo: str
    timestamp: float
    problemas: list[str] = field(default_factory=list)
    aprovada: bool = False


@dataclass
class Etapa:
    """Unidade atômica de raciocínio: uma pergunta → uma resposta de código."""
    numero: int
    descricao: str           # O que esta etapa resolve
    pergunta_cot: str        # Pergunta de raciocínio para o LLM ("O que recebe? Retorna?")
    arquivo: str = ""        # Arquivo de saída (se aplicável)
    dependencias: list[str] = field(default_factory=list)  # Etapas anteriores necessárias
    status: StatusEtapa = StatusEtapa.PENDENTE
    tentativas: list[TentativaEtapa] = field(default_factory=list)
    codigo_aceito: str = ""
    decisoes_locais: list[str] = field(default_factory=list)  # Micro-decisões desta etapa

    @property
    def ultima_tentativa(self) -> Optional[TentativaEtapa]:
        return self.tentativas[-1] if self.tentativas else None

    @property
    def num_tentativas(self) -> int:
        return len(self.tentativas)

    def contexto_para_llm(self, etapas_anteriores: list["Etapa"]) -> str:
        """
        Monta o contexto COMPACTO desta etapa para passar ao LLM.

        Inclui:
        - Pergunta de Chain-of-Thought (força raciocínio antes de gerar código)
        - Código das dependências (truncado às assinaturas)
        - Problema de qualquer tentativa anterior (para re-tentativa)

        Mantém < 500 tokens para compatibilidade com modelos 4K context.
        """
        partes: list[str] = []

        # CoT compacto: força o modelo a pensar antes de gerar
        partes.append(
            f"RACIOCÍNIO ANTES DO CÓDIGO:\n{self.pergunta_cot}\n"
            f"(Responda em 2 linhas, depois gere o código.)"
        )

        # Contexto das dependências (somente assinaturas)
        for dep_num in self.dependencias:
            dep = next((e for e in etapas_anteriores if e.numero == dep_num), None)
            if dep and dep.codigo_aceito:
                assinatura = _extrair_assinatura_compacta(dep.codigo_aceito, dep.arquivo)
                if assinatura:
                    partes.append(f"DEP (etapa {dep_num} — {dep.arquivo}):\n{assinatura}")

        # Feedback da tentativa anterior (se houver)
        if self.ultima_tentativa and not self.ultima_tentativa.aprovada:
            problemas_str = "; ".join(self.ultima_tentativa.problemas[:3])
            partes.append(
                f"TENTATIVA ANTERIOR FALHOU: {problemas_str}\n"
                f"Corrija especificamente esses problemas."
            )

        partes.append(f"TAREFA: {self.descricao}")
        if self.arquivo:
            partes.append(f"GERE: {self.arquivo}")

        return "\n\n".join(partes)


@dataclass
class PlanoRaciocinio:
    """Estado completo do raciocínio em andamento."""
    problema: str
    etapas: list[Etapa] = field(default_factory=list)
    etapa_atual: int = 0
    decisoes_globais: list[str] = field(default_factory=list)
    inicio: float = field(default_factory=time.time)
    concluido: bool = False

    @property
    def progresso(self) -> str:
        feitas = sum(1 for e in self.etapas if e.status == StatusEtapa.CONCLUIDA)
        return f"{feitas}/{len(self.etapas)}"

    @property
    def etapa_pendente(self) -> Optional[Etapa]:
        for e in self.etapas:
            if e.status in (StatusEtapa.PENDENTE, StatusEtapa.EM_PROGRESSO, StatusEtapa.COM_PROBLEMA):
                return e
        return None

    def etapa_por_numero(self, numero: int) -> Optional[Etapa]:
        return next((e for e in self.etapas if e.numero == numero), None)

    def etapas_concluidas(self) -> list[Etapa]:
        return [e for e in self.etapas if e.status == StatusEtapa.CONCLUIDA]


# ══════════════════════════════════════════════════════════════
# SERIALIZAÇÃO (JSON simples, sem SQLAlchemy — hardware fraco)
# ══════════════════════════════════════════════════════════════


def _salvar_plano(plano: PlanoRaciocinio) -> None:
    """Persiste plano em JSON atômico."""
    RACIOCINIO_DB.parent.mkdir(parents=True, exist_ok=True)
    dados = {
        "problema": plano.problema,
        "etapa_atual": plano.etapa_atual,
        "decisoes_globais": plano.decisoes_globais,
        "inicio": plano.inicio,
        "concluido": plano.concluido,
        "etapas": [
            {
                "numero": e.numero,
                "descricao": e.descricao,
                "pergunta_cot": e.pergunta_cot,
                "arquivo": e.arquivo,
                "dependencias": e.dependencias,
                "status": e.status.value,
                "codigo_aceito": e.codigo_aceito,
                "decisoes_locais": e.decisoes_locais,
                "tentativas": [
                    {
                        "codigo": t.codigo,
                        "timestamp": t.timestamp,
                        "problemas": t.problemas,
                        "aprovada": t.aprovada,
                    }
                    for t in e.tentativas[-MAX_HISTORICO_ETAPA:]  # Limita histórico
                ],
            }
            for e in plano.etapas
        ],
    }
    tmp = RACIOCINIO_DB.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(RACIOCINIO_DB)


def _carregar_plano() -> Optional[PlanoRaciocinio]:
    """Restaura plano do JSON se existir."""
    if not RACIOCINIO_DB.exists():
        return None
    try:
        dados = json.loads(RACIOCINIO_DB.read_text(encoding="utf-8"))
        etapas = [
            Etapa(
                numero=e["numero"],
                descricao=e["descricao"],
                pergunta_cot=e.get("pergunta_cot", f"O que a etapa {e['numero']} precisa fazer?"),
                arquivo=e.get("arquivo", ""),
                dependencias=e.get("dependencias", []),
                status=StatusEtapa(e.get("status", "pendente")),
                codigo_aceito=e.get("codigo_aceito", ""),
                decisoes_locais=e.get("decisoes_locais", []),
                tentativas=[
                    TentativaEtapa(
                        codigo=t["codigo"],
                        timestamp=t["timestamp"],
                        problemas=t.get("problemas", []),
                        aprovada=t.get("aprovada", False),
                    )
                    for t in e.get("tentativas", [])
                ],
            )
            for e in dados.get("etapas", [])
        ]
        return PlanoRaciocinio(
            problema=dados["problema"],
            etapas=etapas,
            etapa_atual=dados.get("etapa_atual", 0),
            decisoes_globais=dados.get("decisoes_globais", []),
            inicio=dados.get("inicio", time.time()),
            concluido=dados.get("concluido", False),
        )
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Falha ao carregar plano de raciocínio: %s", exc)
        return None


def _limpar_plano() -> None:
    if RACIOCINIO_DB.exists():
        RACIOCINIO_DB.unlink()


# ══════════════════════════════════════════════════════════════
# VALIDAÇÃO DETERMINÍSTICA (zero custo de LLM)
# ══════════════════════════════════════════════════════════════


def _validar_codigo(codigo: str, arquivo: str) -> list[str]:
    """
    Validação multi-camada sem LLM:
      1. Sintaxe Python via ast.parse (~1ms)
      2. Detecção de stubs (pass/TODO sem corpo real)
      3. Tipo de conteúdo errado (Python em CSS, HTML em .py, etc.)
      4. Degeneração (repetição excessiva de linhas)

    Retorna lista de problemas encontrados (vazia = código OK).
    """
    problemas: list[str] = []

    if not codigo or len(codigo.strip()) < MIN_CHARS_CODIGO_VALIDO:
        return ["código vazio ou muito curto"]

    # 1. Validação de tipo de conteúdo
    if arquivo == "requirements.txt":
        if any(kw in codigo for kw in ("def ", "class ", "import ", "@app")):
            return ["requirements.txt contém código Python; use apenas nomes de pacotes (ex: flask>=3.0)"]

    if arquivo.endswith(".py"):
        if codigo.strip().startswith(("<!DOCTYPE", "<html", "<body")):
            return [f"{arquivo}: contém HTML mas deveria ser Python"]

    if arquivo.endswith(".css"):
        if any(kw in codigo for kw in ("def ", "from flask", "import ")):
            return [f"{arquivo}: contém código Python mas deveria ser CSS"]

    # 2. Sintaxe Python
    if arquivo.endswith(".py"):
        try:
            ast.parse(codigo)
        except SyntaxError as exc:
            return [f"SyntaxError linha {exc.lineno}: {exc.msg}"]

    # 3. Stubs / código incompleto
    linhas = codigo.split("\n")
    linhas_stub = sum(
        1 for ln in linhas
        if any(s in ln for s in SINAIS_STUB) and len(ln.strip()) < 60
    )
    if linhas_stub > 2 and len(codigo) < 400:
        problemas.append(f"{linhas_stub} linhas stub/incompletas detectadas")

    # 4. Degeneração: > 5 linhas idênticas consecutivas
    for i in range(len(linhas) - 4):
        if len(set(linhas[i:i+5])) == 1 and linhas[i].strip():
            problemas.append("degeneração: repetição excessiva de linhas (modelo travou)")
            break

    return problemas


def _extrair_assinatura_compacta(codigo: str, arquivo: str) -> str:
    """
    Extrai apenas imports + defs + classes de um bloco de código.
    Resultado cabe em ~200 tokens — suficiente para o LLM entender a interface.
    """
    if not arquivo.endswith(".py"):
        return "\n".join(codigo.split("\n")[:15])

    try:
        tree = ast.parse(codigo)
    except SyntaxError:
        return "\n".join(codigo.split("\n")[:10])

    linhas: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            linhas.append(f"import {', '.join(a.name for a in node.names)}")
        elif isinstance(node, ast.ImportFrom):
            nomes = ", ".join(a.name for a in node.names)
            linhas.append(f"from {node.module} import {nomes}")
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases) if node.bases else ""
            linhas.append(f"class {node.name}({bases}):")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = ", ".join(a.arg for a in item.args.args)
                    linhas.append(f"    def {item.name}({args}): ...")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.col_offset == 0:
                args = ", ".join(a.arg for a in node.args.args)
                linhas.append(f"def {node.name}({args}): ...")

    return "\n".join(linhas[:40])


# ══════════════════════════════════════════════════════════════
# GERAÇÃO DE PERGUNTAS CoT POR TIPO DE ARQUIVO
# ══════════════════════════════════════════════════════════════


def _gerar_pergunta_cot(descricao: str, arquivo: str, objetivo_projeto: str) -> str:
    """
    Gera a pergunta de Chain-of-Thought específica para o tipo de arquivo.

    Modelos pequenos (1.2B–4B) respondem melhor quando forçados a
    raciocinar sobre entradas/saídas antes de gerar código.
    O custo é ~30 tokens a mais no contexto.
    """
    if arquivo.endswith(".py") and arquivo not in ("requirements.txt",):
        return (
            f"Para '{descricao}':\n"
            f"1. Quais dados esta função/classe recebe como entrada?\n"
            f"2. O que ela deve retornar ou modificar?\n"
            f"3. Qual é o caso de uso mais simples para testar?"
        )

    if arquivo == "requirements.txt":
        return (
            f"Para o projeto '{objetivo_projeto}':\n"
            f"1. Quais bibliotecas externas (não stdlib) serão importadas nos .py?\n"
            f"2. Liste apenas os nomes dos pacotes pip necessários."
        )

    if arquivo.endswith(".html"):
        return (
            f"Para '{descricao}':\n"
            f"1. Quais dados dinâmicos este template precisa exibir?\n"
            f"2. Quais ações o usuário pode fazer (forms, botões)?"
        )

    if arquivo.endswith((".js", ".ts")):
        return (
            f"Para '{descricao}':\n"
            f"1. Quais eventos DOM esta função precisa escutar?\n"
            f"2. Quais dados ela envia ou recebe do servidor?"
        )

    # Genérico
    return f"Para '{descricao}': qual é o propósito exato deste arquivo e o que ele deve conter?"


# ══════════════════════════════════════════════════════════════
# INTERFACE PÚBLICA DA FERRAMENTA
# ══════════════════════════════════════════════════════════════


def iniciar_raciocinio(
    problema: str,
    etapas_raw: list[dict],
) -> PlanoRaciocinio:
    """
    Cria e persiste um novo plano de raciocínio.

    Args:
        problema:   Descrição do problema/projeto a resolver.
        etapas_raw: Lista de dicts com keys: descricao, arquivo, dependencias.
                    Gerada pelo LLM (CoT planejamento) ou pelo template engine.

    Returns:
        PlanoRaciocinio populado e persistido em disco.
    """
    etapas = [
        Etapa(
            numero=i,
            descricao=e["descricao"],
            pergunta_cot=_gerar_pergunta_cot(e["descricao"], e.get("arquivo", ""), problema),
            arquivo=e.get("arquivo", ""),
            dependencias=e.get("dependencias", []),
        )
        for i, e in enumerate(etapas_raw[:MAX_ETAPAS], 1)
    ]

    plano = PlanoRaciocinio(problema=problema, etapas=etapas)
    _salvar_plano(plano)
    logger.info("Raciocínio iniciado: %d etapas para '%s'", len(etapas), problema[:60])
    return plano


def obter_etapa_atual() -> Optional[dict]:
    """
    Retorna contexto pronto para passar ao LLM da etapa pendente.

    Returns:
        Dict com:
          - etapa_numero: int
          - descricao: str
          - arquivo: str
          - contexto_llm: str  ← prompt pronto, com CoT + deps + feedback
          - tentativas_anteriores: int
          - status: str
        Ou None se não houver plano ativo ou plano já concluído.
    """
    plano = _carregar_plano()
    if not plano:
        return None

    etapa = plano.etapa_pendente
    if not etapa:
        return None

    etapa.status = StatusEtapa.EM_PROGRESSO
    _salvar_plano(plano)

    return {
        "etapa_numero": etapa.numero,
        "descricao": etapa.descricao,
        "arquivo": etapa.arquivo,
        "contexto_llm": etapa.contexto_para_llm(plano.etapas_concluidas()),
        "tentativas_anteriores": etapa.num_tentativas,
        "status": etapa.status.value,
        "progresso": plano.progresso,
    }


def registrar_resultado(
    numero_etapa: int,
    codigo: str,
    aprovado: bool = True,
    problemas: Optional[list[str]] = None,
    decisoes: Optional[list[str]] = None,
) -> dict:
    """
    Registra o resultado de uma etapa (código gerado pelo LLM).

    Executa validação determinística mesmo quando aprovado=True
    para capturar problemas óbvios (stubs, degeneração) sem custo de LLM.

    Returns:
        Dict com: sucesso, problemas_encontrados, proxima_etapa (numero ou None)
    """
    plano = _carregar_plano()
    if not plano:
        return {"sucesso": False, "problemas_encontrados": ["plano não encontrado"], "proxima_etapa": None}

    etapa = plano.etapa_por_numero(numero_etapa)
    if not etapa:
        return {"sucesso": False, "problemas_encontrados": [f"etapa {numero_etapa} não existe"], "proxima_etapa": None}

    # Validação determinística (sem LLM)
    problemas_det = _validar_codigo(codigo, etapa.arquivo)
    todos_problemas = (problemas or []) + problemas_det

    tentativa = TentativaEtapa(
        codigo=codigo,
        timestamp=time.time(),
        problemas=todos_problemas,
        aprovada=aprovado and not problemas_det,
    )
    etapa.tentativas.append(tentativa)

    if tentativa.aprovada:
        etapa.codigo_aceito = codigo
        etapa.status = StatusEtapa.CONCLUIDA
        if decisoes:
            etapa.decisoes_locais.extend(decisoes)
        logger.info("Etapa %d concluída: %s", numero_etapa, etapa.descricao[:50])
    else:
        etapa.status = StatusEtapa.COM_PROBLEMA
        logger.debug("Etapa %d com problema: %s", numero_etapa, todos_problemas)

    _salvar_plano(plano)

    # Determina próxima etapa
    proxima = plano.etapa_pendente
    return {
        "sucesso": tentativa.aprovada,
        "problemas_encontrados": todos_problemas,
        "proxima_etapa": proxima.numero if proxima else None,
        "progresso": plano.progresso,
    }


def verificar_etapa(numero_etapa: int, codigo: str) -> dict:
    """
    Verifica código de uma etapa SEM registrar resultado.
    Útil para pré-validação antes de chamar o LLM de validação semântica.

    Returns:
        Dict com: valido, problemas, sugestao_cot
    """
    plano = _carregar_plano()
    if not plano:
        return {"valido": False, "problemas": ["plano não encontrado"], "sugestao_cot": ""}

    etapa = plano.etapa_por_numero(numero_etapa)
    if not etapa:
        return {"valido": False, "problemas": [f"etapa {numero_etapa} não existe"], "sugestao_cot": ""}

    problemas = _validar_codigo(codigo, etapa.arquivo)

    # Sugestão CoT baseada nos problemas encontrados
    sugestao_cot = ""
    if problemas:
        if any("SyntaxError" in p for p in problemas):
            sugestao_cot = "Antes de reescrever, identifique a linha com erro e o que está faltando (parêntese, dois-pontos, indentação)."
        elif any("stub" in p.lower() or "incompleta" in p.lower() for p in problemas):
            sugestao_cot = "O código tem implementações incompletas. Expanda cada função com lógica real antes de retornar."
        elif any("degeneração" in p.lower() or "repetição" in p.lower() for p in problemas):
            sugestao_cot = "O modelo entrou em loop. Recomece a geração com temperatura menor e contexto mais curto."
        else:
            sugestao_cot = "Revise o código identificando o problema específico antes de reescrever."

    return {
        "valido": len(problemas) == 0,
        "problemas": problemas,
        "sugestao_cot": sugestao_cot,
    }


def retroceder(numero_etapa: int) -> dict:
    """
    Regride uma etapa: apaga código aceito e reseta status para pendente.
    Preserva histórico de tentativas para análise.

    Útil quando o usuário ou o self-correction loop detecta que uma etapa
    concluída está errada (ex: integração quebrou ao avançar).

    Returns:
        Dict com: sucesso, etapa_resetada, contexto_llm
    """
    plano = _carregar_plano()
    if not plano:
        return {"sucesso": False, "etapa_resetada": numero_etapa, "contexto_llm": ""}

    etapa = plano.etapa_por_numero(numero_etapa)
    if not etapa:
        return {"sucesso": False, "etapa_resetada": numero_etapa, "contexto_llm": ""}

    etapa.codigo_aceito = ""
    etapa.status = StatusEtapa.PENDENTE
    # Marca última tentativa como não aprovada (para feedback no próximo contexto)
    if etapa.tentativas:
        etapa.tentativas[-1].aprovada = False
        if not etapa.tentativas[-1].problemas:
            etapa.tentativas[-1].problemas = ["retrocedido manualmente — revisar lógica"]

    _salvar_plano(plano)
    logger.info("Etapa %d revertida para pendente", numero_etapa)

    return {
        "sucesso": True,
        "etapa_resetada": numero_etapa,
        "contexto_llm": etapa.contexto_para_llm(plano.etapas_concluidas()),
    }


def obter_contexto_completo() -> dict:
    """
    Retorna estado completo do plano para diagnóstico ou exibição na CLI.

    Returns:
        Dict com: problema, progresso, etapas (lista resumida), concluido
    """
    plano = _carregar_plano()
    if not plano:
        return {"erro": "nenhum plano de raciocínio ativo"}

    return {
        "problema": plano.problema,
        "progresso": plano.progresso,
        "concluido": plano.concluido,
        "decisoes_globais": plano.decisoes_globais,
        "etapas": [
            {
                "numero": e.numero,
                "descricao": e.descricao,
                "arquivo": e.arquivo,
                "status": e.status.value,
                "tentativas": e.num_tentativas,
                "tem_codigo": bool(e.codigo_aceito),
            }
            for e in plano.etapas
        ],
    }


def finalizar_raciocinio() -> dict:
    """
    Finaliza o plano atual e retorna sumário.
    Limpa persistência após conclusão.

    Returns:
        Dict com: problema, etapas_concluidas, etapas_puladas, arquivos_gerados, tempo_s
    """
    plano = _carregar_plano()
    if not plano:
        return {"erro": "nenhum plano ativo para finalizar"}

    plano.concluido = True
    _salvar_plano(plano)

    sumario = {
        "problema": plano.problema,
        "etapas_concluidas": sum(1 for e in plano.etapas if e.status == StatusEtapa.CONCLUIDA),
        "etapas_puladas": sum(1 for e in plano.etapas if e.status == StatusEtapa.PULADA),
        "arquivos_gerados": {
            e.arquivo: len(e.codigo_aceito)
            for e in plano.etapas
            if e.codigo_aceito and e.arquivo
        },
        "tempo_s": round(time.time() - plano.inicio, 1),
        "total_tentativas": sum(e.num_tentativas for e in plano.etapas),
    }

    _limpar_plano()
    logger.info("Raciocínio finalizado: %s", sumario)
    return sumario


def existe_plano_ativo() -> bool:
    """Verifica se há plano de raciocínio em andamento."""
    plano = _carregar_plano()
    return plano is not None and not plano.concluido
