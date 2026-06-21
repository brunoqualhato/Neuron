"""
Motor de execução dos agentes com 3 níveis de performance.

Pipeline por nível:
  Nível 1: Ferramentas → Cache → ChromaDB → RETORNA (sem LLM!)
  Nível 2: ...nivel1... → Modelo Rápido (1.7B) + contexto mínimo
  Nível 3: ...nivel1... → ChromaDB RAG → Modelo Completo (4B) + contexto rico
"""

import time
from rich.console import Console
from rich.panel import Panel

from src.core.config import (
    AGENTES,
    NIVEIS,
    CHROMADB_NIVEL1_THRESHOLD,
    RAG_MAX_CHARS,
    RAG_MAX_DOCS,
    SINAIS_WEB,
)
from src.core.utils import normalizar
from src.core.classificador import classificar_complexidade, explicar_nivel
from src.core.llm import chamar_llm, resumir_conversa, verificar_modelo_disponivel
from src.memoria.cache import Cache
from src.memoria.sqlite import Memoria
from src.memoria.semantica import MemoriaSemantica
from src.ferramentas.resolver import executar_ferramentas
from src.ferramentas.web import pesquisar_web, pesquisar_clima, pesquisar_documentacao, pesquisar_cotacao

console = Console()


class SistemaAgentes:
    """Gerencia a execução dos agentes com 3 níveis de performance."""

    def __init__(self):
        self.memoria = Memoria()
        self.cache = Cache()
        self.semantica = MemoriaSemantica()
        self.nivel_forcado: int | None = None

    def executar(self, nome_agente: str, pergunta: str) -> str:
        """Pipeline principal com 3 níveis de performance."""
        agente = AGENTES[nome_agente]
        inicio = time.time()

        # Classificar complexidade
        if self.nivel_forcado:
            nivel = self.nivel_forcado
            self.nivel_forcado = None
        else:
            nivel = classificar_complexidade(pergunta)
            if nivel == 2 and agente.get("nivel_preferido", 2) == 3:
                if len(pergunta.split()) > 12:
                    nivel = 3

        console.print(f"[dim]{explicar_nivel(nivel)}[/dim]")

        # ═══════════════════════════════════════════
        # NÍVEL 1: TURBO (sem LLM)
        # ═══════════════════════════════════════════

        # 1a. Ferramentas diretas
        resultado_ferramenta = executar_ferramentas(pergunta)
        if resultado_ferramenta:
            console.print(
                Panel(resultado_ferramenta, title="⚡ Nível 1 • Ferramenta", border_style="cyan")
            )
            self._salvar(pergunta, resultado_ferramenta, nome_agente, nivel=1, inicio=inicio)
            return resultado_ferramenta

        # 1b. Cache exato — ignorado para dados em tempo real
        cache_key = f"{nome_agente}:{pergunta}"
        precisa_web = self._precisa_web(pergunta)
        resposta_cache = None if precisa_web else self.cache.buscar(cache_key)
        if resposta_cache:
            console.print("[dim]📋 Nível 1 • Cache[/dim]")
            console.print(resposta_cache, style="green")
            self._salvar_metrica(nome_agente, 1, inicio, fonte="cache")
            return resposta_cache

        # 1c. ChromaDB — busca semântica
        docs_similares = self.semantica.buscar_similar(pergunta)
        if docs_similares and nivel == 1:
            melhor = docs_similares[0]
            if melhor.get("score_hibrido", melhor["similaridade"]) >= CHROMADB_NIVEL1_THRESHOLD:
                resposta = melhor["conteudo"].split("Resposta: ", 1)[-1]
                console.print(
                    f"[dim]🧲 Nível 1 • ChromaDB ({melhor.get('score_hibrido', melhor['similaridade']):.0%})[/dim]"
                )
                console.print(resposta, style="green")
                self._salvar_metrica(nome_agente, 1, inicio, fonte="chromadb")
                return resposta

        # Promover se nível 1 não resolveu
        if nivel == 1:
            nivel = 2
            console.print("[dim]↑ Promovido para Nível 2[/dim]")

        # ═══════════════════════════════════════════
        # NÍVEL 2: RÁPIDO (modelo 1.7B)
        # ═══════════════════════════════════════════

        if nivel == 2:
            contexto_busca = ""
            if nome_agente == "pesquisador" or precisa_web:
                console.print("[dim]🔍 Pesquisando na web...[/dim]")
                contexto_busca = self._buscar_web_contextual(pergunta, max_resultados=3)

            mensagens = self._montar_contexto(2, contexto_busca, pergunta)

            resultado = chamar_llm(
                modelo=agente["modelo_rapido"],
                system_prompt=agente["system_prompt"],
                mensagens=mensagens,
                stream=True,
                max_tokens=512,
                temperatura=0.4,
            )

            self._salvar(pergunta, resultado["resposta"], nome_agente, nivel=2, inicio=inicio)
            self._salvar_metrica(
                nome_agente, 2, inicio,
                tokens_in=resultado["tokens_entrada"],
                tokens_out=resultado["tokens_saida"],
                fonte="llm_rapido",
            )
            if self._deve_promover_para_profundo(pergunta, resultado["resposta"]):
                console.print("[dim]↑ Ajuste de precisão: promovido para Nível 3[/dim]")
                nivel = 3
            else:
                return resultado["resposta"]

        # ═══════════════════════════════════════════
        # NÍVEL 3: PROFUNDO (modelo 4B + RAG)
        # ═══════════════════════════════════════════

        contexto_busca = ""
        if nome_agente == "pesquisador" or precisa_web:
            console.print("[dim]🔍 Pesquisando na web...[/dim]")
            contexto_busca = self._buscar_web_contextual(pergunta, max_resultados=5)

        # RAG: enriquecer com ChromaDB
        contexto_rag = ""
        if docs_similares:
            docs_rag = docs_similares[:RAG_MAX_DOCS]
            console.print(f"[dim]🧲 RAG: {len(docs_rag)} docs do ChromaDB[/dim]")
            contexto_rag = self._construir_contexto_rag(docs_rag)

        mensagens = self._montar_contexto(
            n_msgs=5,
            contexto_busca=contexto_busca,
            pergunta=pergunta,
            contexto_rag=contexto_rag,
        )

        modelo_profundo = agente["modelo_profundo"]
        if not verificar_modelo_disponivel(modelo_profundo):
            # Tenta encontrar o melhor modelo instalado antes de cair no rapido
            candidatos = ["qwen3:4b", "qwen2.5:3b", "llama3.2:3b", agente["modelo_rapido"]]
            modelo_profundo = next(
                (m for m in candidatos if verificar_modelo_disponivel(m)),
                agente["modelo_rapido"],
            )
            console.print(
                f"[yellow]⚠️  Modelo profundo '{agente['modelo_profundo']}' não instalado. "
                f"Usando '{modelo_profundo}' como fallback.[/yellow]"
            )

        resultado = chamar_llm(
            modelo=modelo_profundo,
            system_prompt=self._system_prompt_com_rag(agente["system_prompt"], bool(contexto_rag)),
            mensagens=mensagens,
            stream=True,
            max_tokens=2048,
            temperatura=0.7,
        )

        self._salvar(pergunta, resultado["resposta"], nome_agente, nivel=3, inicio=inicio)
        self._salvar_metrica(
            nome_agente, 3, inicio,
            tokens_in=resultado["tokens_entrada"],
            tokens_out=resultado["tokens_saida"],
            fonte="llm_profundo",
        )

        # Resumo automático
        if self.memoria.total_mensagens() % 10 == 0:
            self._gerar_resumo(agente["modelo_rapido"])

        return resultado["resposta"]

    def _system_prompt_com_rag(self, base_prompt: str, tem_rag: bool) -> str:
        """Aplica instruções de grounding quando houver contexto recuperado."""
        if not tem_rag:
            return base_prompt
        complemento = (
            "\n\nUse primeiro o contexto recuperado para responder com precisão. "
            "Se o contexto for insuficiente, sinalize explicitamente o que falta em vez de inventar fatos. "
            "Quando possível, cite trechos do contexto recuperado."
        )
        return f"{base_prompt}{complemento}"

    def _construir_contexto_rag(self, docs: list[dict]) -> str:
        """Compacta o contexto RAG para reduzir ruído sem perder cobertura."""
        blocos: list[str] = []
        total_chars = 0
        for idx, doc in enumerate(docs, 1):
            score = doc.get("score_hibrido", doc.get("similaridade", 0.0))
            conteudo = doc.get("conteudo", "").strip()
            if not conteudo:
                continue

            # Mantém o contexto dentro de um limite para proteger qualidade no modelo menor.
            trecho = conteudo[:900]
            bloco = f"[Doc {idx} | Score {score:.0%}]\n{trecho}"

            if total_chars + len(bloco) > RAG_MAX_CHARS:
                break

            blocos.append(bloco)
            total_chars += len(bloco)

        return "\n\n".join(blocos)

    @staticmethod
    def _precisa_web(pergunta: str) -> bool:
        """Detecta se a pergunta requer dados em tempo real ou documentação externa."""
        texto = normalizar(pergunta)
        return any(normalizar(sinal) in texto for sinal in SINAIS_WEB)

    @staticmethod
    def _buscar_web_contextual(pergunta: str, max_resultados: int = 3) -> str:
        """Escolhe a ferramenta de busca mais adequada para o tipo de consulta."""
        texto = pergunta.lower()

        # Clima / temperatura
        _termos_clima = ["temperatura", "clima em", "tempo em", "previsão do tempo",
                         "vai chover", "chuva em", "calor em", "frio em", "umidade"]
        if any(t in texto for t in _termos_clima):
            import re
            # Tenta extrair cidade da pergunta
            m = re.search(
                r"(?:em|n[ao]|para|de)\s+([A-Za-zÀ-ú]{3,}(?:\s+[A-Za-zÀ-ú]{2,})?)",
                pergunta, re.IGNORECASE
            )
            cidade = m.group(1) if m else pergunta
            return pesquisar_clima(cidade)

        # Documentação
        _termos_docs = ["documentação", "docs", "manual", "referência", "how to",
                        "tutorial de", "tutorial do", "guia de", "guia do",
                        "como instalar", "como usar", "como configurar", "api do", "api de"]
        if any(t in texto for t in _termos_docs):
            return pesquisar_documentacao(pergunta, max_resultados)

        # Cotações
        _termos_cotacao = ["cotação", "dólar", "euro", "bitcoin", "câmbio",
                           "bolsa", "ibovespa", "nasdaq", "selic", "cripto"]
        if any(t in texto for t in _termos_cotacao):
            return pesquisar_cotacao(pergunta)

        # Genérico
        return pesquisar_web(pergunta, max_resultados)

    @staticmethod
    def _deve_promover_para_profundo(pergunta: str, resposta: str) -> bool:
        """Promove para nível profundo quando a saída rápida é fraca para a pergunta."""
        if not resposta:
            return True

        resposta_lower = resposta.lower().strip()
        pergunta_tokens = len(pergunta.split())

        sinais_incerteza = [
            "não sei",
            "não tenho informação",
            "não encontrei",
            "não posso afirmar",
            "não posso fornecer",
            "não consigo fornecer",
            "não tenho acesso",
            "não possuo acesso",
            "recomendo consultar",
            "talvez",
            "depende",
        ]
        if any(s in resposta_lower for s in sinais_incerteza):
            return True

        if pergunta_tokens >= 14 and len(resposta_lower) < 120:
            return True

        return False

    def _montar_contexto(
        self, n_msgs: int, contexto_busca: str, pergunta: str, contexto_rag: str = ""
    ) -> list[dict]:
        """Monta lista de mensagens para o LLM."""
        mensagens = []

        resumo = self.memoria.ultimo_resumo()
        if resumo:
            mensagens.append({
                "role": "system",
                "content": f"Contexto anterior: {resumo}"
            })

        if contexto_rag:
            mensagens.append({
                "role": "system",
                "content": f"Conhecimento relevante da base:\n{contexto_rag}"
            })

        # Resultados web como system message — garante que modelos pequenos não ignorem
        if contexto_busca:
            mensagens.append({
                "role": "system",
                "content": (
                    "DADOS ATUAIS OBTIDOS DA WEB — use exclusivamente estes dados para responder. "
                    "NUNCA diga que não tem acesso a informações em tempo real quando estes dados estiverem presentes.\n\n"
                    f"{contexto_busca}"
                ),
            })

        historico = self.memoria.ultimas_mensagens(n_msgs)
        for msg in historico:
            mensagens.append({"role": msg["role"], "content": msg["content"]})

        # Para modelos pequenos: inclui dados também na mensagem user para garantir grounding
        if contexto_busca:
            conteudo = (
                f"{pergunta}\n\n"
                f"[Dados obtidos agora da web — responda com base exclusivamente nestes dados]:\n"
                f"{contexto_busca[:1500]}"
            )
        else:
            conteudo = pergunta

        mensagens.append({"role": "user", "content": conteudo})

        return mensagens

    def _salvar(self, pergunta: str, resposta: str, agente: str, nivel: int, inicio: float):
        """Salva em todas as camadas de memória."""
        self.memoria.salvar_mensagem("user", pergunta)
        self.memoria.salvar_mensagem("assistant", resposta, agente, nivel)
        cache_key = f"{agente}:{pergunta}"
        self.cache.salvar(cache_key, resposta, agente)
        self.semantica.adicionar(pergunta, resposta, agente)

    def _salvar_metrica(self, agente: str, nivel: int, inicio: float,
                        tokens_in: int = 0, tokens_out: int = 0, fonte: str = ""):
        """Salva métrica de performance."""
        tempo_ms = int((time.time() - inicio) * 1000)
        self.memoria.salvar_metrica(agente, nivel, tempo_ms, tokens_in, tokens_out, fonte)

    def _gerar_resumo(self, modelo: str):
        """Gera resumo automático."""
        mensagens = self.memoria.ultimas_mensagens(10)
        if mensagens:
            console.print("[dim]📝 Resumo automático...[/dim]")
            resumo = resumir_conversa(modelo, mensagens)
            if resumo:
                self.memoria.salvar_resumo(resumo)

    def forcar_nivel(self, nivel: int):
        """Força nível para a próxima pergunta."""
        if nivel in (1, 2, 3):
            self.nivel_forcado = nivel

    def estatisticas(self) -> dict:
        """Retorna estatísticas completas."""
        return {
            "cache": self.cache.estatisticas(),
            "chromadb": self.semantica.estatisticas(),
            "metricas": self.memoria.metricas_resumo(),
            "mensagens_total": self.memoria.total_mensagens(),
        }

    def ingerir_conhecimento(self, texto: str, fonte: str = ""):
        """Adiciona conhecimento à base vetorial."""
        self.semantica.adicionar_conhecimento(texto, fonte)
        console.print(f"[green]📚 Conhecimento adicionado ({len(texto)} chars)[/green]")

    def fechar(self):
        self.memoria.fechar()
