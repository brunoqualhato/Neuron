# Fase 1 - Fundação (provedores + bus + CI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar a fundação do fork local-first: abstração de provider de LLM (Ollama default), message bus assíncrono e CI, sem quebrar os 111 testes existentes.

**Architecture:** Camadas aditivas. O core (`src/agentes`, `src/core`, `src/memoria`, `src/ferramentas`) permanece intacto. Adicionamos `src/provedores/` (abstração de LLM) e `src/conexoes/bus.py` (transporte). `src/core/llm.py` vira uma fachada fina que delega ao provider resolvido por um registry, preservando suas assinaturas públicas para que `executor.py`/`main.py` não mudem.

**Tech Stack:** Python 3.11+, ollama, rich, pytest, pytest-mock, ruff, asyncio. litellm como extra opcional (desligado por padrão).

## Global Constraints

- Python 3.11+ (sintaxe `X | None`, `list[dict]` já em uso no código).
- Offline-first: nenhuma dependência nova no caminho padrão. `litellm` é extra opcional, importado de forma lazy, nunca no path default.
- PC fraco: nada residente competindo RAM. O `OllamaProvider` preserva e expõe o tuning (`num_ctx`, `num_thread`, `keep_alive` efêmero, `timeout`).
- Não-regressão é gate: os 111 testes existentes continuam verdes em toda tarefa.
- Compatibilidade: manter as assinaturas públicas de `src/core/llm.py` (`chamar_llm`, `chamar_coordenador`, `resumir_conversa`, `verificar_modelo_disponivel`, `warmup_modelos`) e seus retornos (dict para `chamar_llm`).
- Provider default = `ollama`. Sem fallback cloud automático.
- Textos visíveis em pt-BR com acentos corretos. Sem em dashes. Sem Co-Authored-By nos commits.
- Ambiente de teste: venv em `.venv`. Comandos rodam via `.venv/bin/python -m pytest` e `.venv/bin/ruff`.

---

### Task 1: Sincronizar fork + baseline verde

**Files:**
- Modify: working tree (git) e `.venv/` (ambiente)

**Interfaces:**
- Consumes: nada
- Produces: ambiente `.venv` com deps-dev instaladas; baseline de 111 testes verde registrada.

- [ ] **Step 1: Sincronizar o fork com o upstream do Bruno**

Estamos na branch `design/hub-conexoes`. Trazer os 2 commits do upstream para a base de trabalho.

```bash
cd ~/potato-claw
git fetch upstream
git checkout main
git merge --ff-only upstream/main
git checkout -b feat/fase-1-fundacao
```

Expected: `main` atualizada sem conflito; nova branch `feat/fase-1-fundacao` criada a partir da main sincronizada.

- [ ] **Step 2: Criar venv e instalar dependências de desenvolvimento**

```bash
cd ~/potato-claw
uv venv .venv
.venv/bin/python -m pip install --upgrade pip
uv pip install --python .venv/bin/python -r requirements-dev.txt
```

Expected: instalação OK de ollama, rich, chromadb, ddgs, pytest, pytest-mock, ruff.

- [ ] **Step 3: Rodar a suíte completa e registrar a baseline**

```bash
.venv/bin/python -m pytest -q
```

Expected: 111 passed (ou o número atual após o merge). Anotar o número exato como baseline. Se algum teste falhar por ambiente (ex.: ChromaDB/embeddings), registrar quais e tratar como pré-existente, não introduzido por esta fase.

- [ ] **Step 4: Commit (marco de baseline)**

Sem mudanças de código ainda; o commit registra apenas o ponto de partida se o merge trouxe arquivos. Se nada mudou no working tree, pular o commit.

```bash
git add -A && git commit -m "chore: sincroniza fork com upstream e prepara fase 1" || echo "nada a commitar"
```

---

### Task 2: CI (GitHub Actions com pytest + ruff)

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `ruff.toml`

**Interfaces:**
- Consumes: `requirements-dev.txt`
- Produces: workflow `ci` que roda em push/PR; config de lint `ruff.toml`.

- [ ] **Step 1: Criar a config do ruff**

```toml
# ruff.toml
target-version = "py311"
line-length = 100

[lint]
select = ["E", "F", "I", "W"]
ignore = ["E501"]

[lint.isort]
known-first-party = ["src"]
```

- [ ] **Step 2: Rodar ruff localmente para ver o estado atual**

Run: `.venv/bin/ruff check . `
Expected: pode acusar problemas pré-existentes. Se acusar, NÃO corrigir o core agora; em vez disso, no Step 3 o CI roda `ruff check src/provedores src/conexoes tests` (escopo das camadas novas) para não travar no legado. Ajustar o glob abaixo conforme necessário.

- [ ] **Step 3: Criar o workflow de CI**

```yaml
# .github/workflows/ci.yml
name: ci
on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Instalar uv
        run: pip install uv
      - name: Criar venv e instalar deps
        run: |
          uv venv .venv
          uv pip install --python .venv/bin/python -r requirements-dev.txt
      - name: Lint (camadas novas)
        run: .venv/bin/ruff check src/provedores src/conexoes tests || true
      - name: Testes
        run: .venv/bin/python -m pytest -q
```

Nota: o `|| true` no lint é temporário para o legado não travar o merge; remover quando o ruff passar limpo no repo todo (follow-up).

- [ ] **Step 4: Validar o YAML localmente**

Run: `.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"`
Expected: `yaml ok` (instalar pyyaml se faltar: `uv pip install --python .venv/bin/python pyyaml`).

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml ruff.toml
git commit -m "ci: adiciona workflow pytest+ruff e config do ruff"
```

---

### Task 3: RespostaLLM + LLMProvider (ABC)

**Files:**
- Create: `src/provedores/__init__.py`
- Create: `src/provedores/base.py`
- Test: `tests/test_provedores_base.py`

**Interfaces:**
- Consumes: nada
- Produces:
  - `RespostaLLM` (dataclass): campos `resposta: str`, `tempo_ms: int = 0`, `tokens_entrada: int = 0`, `tokens_saida: int = 0`.
  - `LLMProvider` (ABC) com `nome: str` e métodos abstratos:
    - `chat(self, modelo: str, system_prompt: str, mensagens: list[dict], *, stream: bool = True, max_tokens: int = 2048, temperatura: float = 0.7, num_ctx: int | None = None, num_thread: int | None = None, keep_alive: str | None = None, timeout: float | None = None) -> RespostaLLM`
    - `modelo_disponivel(self, modelo: str) -> bool`
    - `warmup(self, modelos: dict[str, str], keep_alive: str = "10m") -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provedores_base.py
import pytest
from src.provedores.base import RespostaLLM, LLMProvider


def test_resposta_llm_tem_defaults():
    r = RespostaLLM(resposta="oi")
    assert r.resposta == "oi"
    assert r.tempo_ms == 0
    assert r.tokens_entrada == 0
    assert r.tokens_saida == 0


def test_llmprovider_nao_instancia_direto():
    with pytest.raises(TypeError):
        LLMProvider()  # ABC com métodos abstratos
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_provedores_base.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.provedores'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/provedores/__init__.py
"""Camada de abstração de provedores de LLM."""
```

```python
# src/provedores/base.py
"""Contrato comum para provedores de LLM (offline-first)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class RespostaLLM:
    """Resultado padronizado de uma chamada ao LLM."""
    resposta: str
    tempo_ms: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0


class LLMProvider(ABC):
    """Interface mínima que todo provider deve cumprir."""
    nome: str = "base"

    @abstractmethod
    def chat(
        self,
        modelo: str,
        system_prompt: str,
        mensagens: list[dict],
        *,
        stream: bool = True,
        max_tokens: int = 2048,
        temperatura: float = 0.7,
        num_ctx: int | None = None,
        num_thread: int | None = None,
        keep_alive: str | None = None,
        timeout: float | None = None,
    ) -> RespostaLLM:
        ...

    @abstractmethod
    def modelo_disponivel(self, modelo: str) -> bool:
        ...

    @abstractmethod
    def warmup(self, modelos: dict[str, str], keep_alive: str = "10m") -> None:
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_provedores_base.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/provedores/__init__.py src/provedores/base.py tests/test_provedores_base.py
git commit -m "feat: contrato LLMProvider e RespostaLLM"
```

---

### Task 4: OllamaProvider

**Files:**
- Create: `src/provedores/ollama_provider.py`
- Test: `tests/test_provedores_ollama.py`

**Interfaces:**
- Consumes: `RespostaLLM`, `LLMProvider` (Task 3); `src.provedores.registry.registrar` (Task 5, ver nota).
- Produces: `OllamaProvider(LLMProvider)` com `nome = "ollama"`. `chat()` retorna `RespostaLLM`; `modelo_disponivel()` retorna bool; `warmup()` pré-carrega. As `options` do Ollama incluem `temperature`, `num_predict=max_tokens`, e quando informados `num_ctx`, `num_thread`. `keep_alive` e `timeout` repassados ao cliente.

Nota de ordem: a chamada de auto-registro (`registrar("ollama", OllamaProvider)`) depende da Task 5. Implementar aqui o provider e adicionar o registro no fim do arquivo apenas após a Task 5 existir; o teste desta task NÃO depende do registry.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provedores_ollama.py
from unittest.mock import patch, MagicMock
from src.provedores.ollama_provider import OllamaProvider
from src.provedores.base import RespostaLLM


@patch("src.provedores.ollama_provider.ollama")
def test_chat_sem_stream_retorna_resposta(mock_ollama):
    mock_ollama.chat.return_value = {
        "message": {"content": "resposta teste"},
        "prompt_eval_count": 7,
        "eval_count": 3,
    }
    p = OllamaProvider()
    r = p.chat("modelo-x", "sys", [{"role": "user", "content": "oi"}], stream=False)
    assert isinstance(r, RespostaLLM)
    assert r.resposta == "resposta teste"
    assert r.tokens_entrada == 7
    assert r.tokens_saida == 3


@patch("src.provedores.ollama_provider.ollama")
def test_chat_passa_num_ctx_e_num_thread_nas_options(mock_ollama):
    mock_ollama.chat.return_value = {"message": {"content": "x"}}
    p = OllamaProvider()
    p.chat("m", "s", [{"role": "user", "content": "oi"}], stream=False,
           num_ctx=1024, num_thread=4, keep_alive="0s")
    _, kwargs = mock_ollama.chat.call_args
    assert kwargs["options"]["num_ctx"] == 1024
    assert kwargs["options"]["num_thread"] == 4
    assert kwargs["keep_alive"] == "0s"


@patch("src.provedores.ollama_provider.ollama")
def test_modelo_disponivel_lista(mock_ollama):
    resp = MagicMock()
    resp.models = [MagicMock(model="qwen3:1.7b")]
    mock_ollama.list.return_value = resp
    p = OllamaProvider()
    assert p.modelo_disponivel("qwen3:1.7b") is True
    assert p.modelo_disponivel("inexistente") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_provedores_ollama.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.provedores.ollama_provider'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/provedores/ollama_provider.py
"""Provider padrão: Ollama local. Preserva o tuning para PC fraco."""
from __future__ import annotations

import time

import ollama
from rich.console import Console

from src.provedores.base import LLMProvider, RespostaLLM

console = Console()


class OllamaProvider(LLMProvider):
    nome = "ollama"

    def chat(
        self,
        modelo: str,
        system_prompt: str,
        mensagens: list[dict],
        *,
        stream: bool = True,
        max_tokens: int = 2048,
        temperatura: float = 0.7,
        num_ctx: int | None = None,
        num_thread: int | None = None,
        keep_alive: str | None = None,
        timeout: float | None = None,
    ) -> RespostaLLM:
        msgs = [{"role": "system", "content": system_prompt}]
        for m in mensagens:
            msgs.append({"role": m["role"], "content": m["content"]})

        options: dict = {"temperature": temperatura, "num_predict": max_tokens}
        if num_ctx is not None:
            options["num_ctx"] = num_ctx
        if num_thread is not None:
            options["num_thread"] = num_thread

        extra: dict = {}
        if keep_alive is not None:
            extra["keep_alive"] = keep_alive

        inicio = time.time()
        resposta = ""
        tokens_in = 0
        tokens_out = 0

        try:
            if stream:
                for chunk in ollama.chat(
                    model=modelo, messages=msgs, stream=True, options=options, **extra
                ):
                    texto = chunk["message"]["content"]
                    resposta += texto
                    console.print(texto, end="", style="green")
                    if "eval_count" in chunk:
                        tokens_out = chunk["eval_count"]
                    if "prompt_eval_count" in chunk:
                        tokens_in = chunk["prompt_eval_count"]
                    if len(resposta) > 300 and resposta[-150:] == resposta[-300:-150]:
                        console.print("\n[dim]⚠️ Repetição detectada, parando.[/dim]")
                        break
                console.print()
            else:
                r = ollama.chat(model=modelo, messages=msgs, options=options, **extra)
                resposta = r["message"]["content"]
                tokens_in = r.get("prompt_eval_count", 0)
                tokens_out = r.get("eval_count", 0)
        except Exception as e:
            resposta = f"Erro ao chamar modelo {modelo}: {e}"
            console.print(f"\n[red]{resposta}[/red]")

        return RespostaLLM(
            resposta=resposta,
            tempo_ms=int((time.time() - inicio) * 1000),
            tokens_entrada=tokens_in,
            tokens_saida=tokens_out,
        )

    def modelo_disponivel(self, modelo: str) -> bool:
        try:
            resposta = ollama.list()
            nomes_raw: list[str] = []
            if isinstance(resposta, dict):
                for m in resposta.get("models", []):
                    if isinstance(m, dict):
                        nomes_raw.append(m.get("name") or m.get("model") or "")
            elif hasattr(resposta, "models"):
                for m in getattr(resposta, "models", []):
                    nomes_raw.append(getattr(m, "model", "") or getattr(m, "name", ""))
            nomes = {n.strip().lower() for n in nomes_raw if n}
            nomes_base = {n.split(":", 1)[0] for n in nomes}
            alvo = modelo.strip().lower()
            alvo_base = alvo.split(":", 1)[0]
            if ":" in alvo:
                return alvo in nomes
            return alvo in nomes or f"{alvo}:latest" in nomes or alvo_base in nomes_base
        except Exception:
            return False

    def warmup(self, modelos: dict[str, str], keep_alive: str = "10m") -> None:
        for modelo in set(modelos.values()):
            try:
                ollama.chat(
                    model=modelo,
                    messages=[{"role": "user", "content": "oi"}],
                    options={"num_predict": 1},
                    keep_alive=keep_alive,
                )
                console.print(f"  [dim]🔥 {modelo} carregado[/dim]")
            except Exception:
                pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_provedores_ollama.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/provedores/ollama_provider.py tests/test_provedores_ollama.py
git commit -m "feat: OllamaProvider com tuning para PC fraco"
```

---

### Task 5: Registry de providers

**Files:**
- Create: `src/provedores/registry.py`
- Modify: `src/provedores/ollama_provider.py` (auto-registro no fim do arquivo)
- Modify: `src/provedores/__init__.py` (importar o provider built-in para disparar registro)
- Test: `tests/test_provedores_registry.py`

**Interfaces:**
- Consumes: `LLMProvider` (Task 3), `OllamaProvider` (Task 4)
- Produces:
  - `registrar(nome: str, classe: type[LLMProvider]) -> None`
  - `criar(nome: str = "ollama", **kwargs) -> LLMProvider`
  - `disponiveis() -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provedores_registry.py
import pytest
import src.provedores  # noqa: F401  (dispara auto-registro)
from src.provedores import registry
from src.provedores.ollama_provider import OllamaProvider


def test_ollama_registrado_por_padrao():
    assert "ollama" in registry.disponiveis()


def test_criar_default_retorna_ollama():
    p = registry.criar()
    assert isinstance(p, OllamaProvider)
    assert p.nome == "ollama"


def test_criar_nome_invalido_levanta():
    with pytest.raises(ValueError):
        registry.criar("nao-existe")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_provedores_registry.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.provedores.registry'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/provedores/registry.py
"""Registro nome -> provider. Default = ollama."""
from __future__ import annotations

from src.provedores.base import LLMProvider

_provedores: dict[str, type[LLMProvider]] = {}


def registrar(nome: str, classe: type[LLMProvider]) -> None:
    _provedores[nome] = classe


def criar(nome: str = "ollama", **kwargs) -> LLMProvider:
    if nome not in _provedores:
        raise ValueError(
            f"Provider '{nome}' nao registrado. Disponiveis: {list(_provedores)}"
        )
    return _provedores[nome](**kwargs)


def disponiveis() -> list[str]:
    return list(_provedores)
```

Adicionar no FIM de `src/provedores/ollama_provider.py`:

```python
from src.provedores import registry as _registry  # noqa: E402

_registry.registrar("ollama", OllamaProvider)
```

Substituir o conteúdo de `src/provedores/__init__.py` por:

```python
# src/provedores/__init__.py
"""Camada de abstração de provedores de LLM."""
from src.provedores import ollama_provider  # noqa: F401  (auto-registra "ollama")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_provedores_registry.py tests/test_provedores_ollama.py -v`
Expected: PASS (registry: 3 passed; ollama: 3 passed). Confirma que não houve import circular.

- [ ] **Step 5: Commit**

```bash
git add src/provedores/registry.py src/provedores/ollama_provider.py src/provedores/__init__.py tests/test_provedores_registry.py
git commit -m "feat: registry de providers com default ollama"
```

---

### Task 6: core/llm.py vira fachada que delega ao registry

**Files:**
- Modify: `src/core/llm.py` (reescrever como fachada fina)
- Test: `tests/test_llm_fachada.py`

**Interfaces:**
- Consumes: `registry.criar` (Task 5), `RespostaLLM` (Task 3)
- Produces: mesmas assinaturas públicas de antes, retornos idênticos:
  - `chamar_llm(...) -> dict` com chaves `resposta`, `tempo_ms`, `tokens_entrada`, `tokens_saida`
  - `chamar_coordenador(pergunta, modelo, system_prompt) -> str`
  - `resumir_conversa(modelo, mensagens) -> str`
  - `verificar_modelo_disponivel(modelo) -> bool`
  - `warmup_modelos(modelos, keep_alive="10m") -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_fachada.py
from unittest.mock import patch, MagicMock
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm_fachada.py -v`
Expected: FAIL (`AttributeError: <module 'src.core.llm'> does not have the attribute '_provider'`).

- [ ] **Step 3: Write minimal implementation**

Reescrever `src/core/llm.py` inteiro:

```python
"""
Fachada de LLM. Delega ao provider resolvido pelo registry (default ollama).
Mantém as assinaturas públicas usadas por executor.py e main.py.
"""
from __future__ import annotations

from rich.console import Console

from src.provedores import registry

console = Console()

# Provider único do processo. Trocável via NEURON_PROVIDER no futuro.
_provider = registry.criar("ollama")


def chamar_llm(
    modelo: str,
    system_prompt: str,
    mensagens: list[dict],
    stream: bool = True,
    max_tokens: int = 2048,
    temperatura: float = 0.7,
) -> dict:
    r = _provider.chat(
        modelo, system_prompt, mensagens,
        stream=stream, max_tokens=max_tokens, temperatura=temperatura,
    )
    return {
        "resposta": r.resposta,
        "tempo_ms": r.tempo_ms,
        "tokens_entrada": r.tokens_entrada,
        "tokens_saida": r.tokens_saida,
    }


def chamar_coordenador(pergunta: str, modelo: str, system_prompt: str) -> str:
    r = _provider.chat(
        modelo, system_prompt, [{"role": "user", "content": pergunta}],
        stream=False, max_tokens=20, temperatura=0.1,
    )
    texto = r.resposta.strip().lower()
    return texto or "analista"


def resumir_conversa(modelo: str, mensagens: list[dict]) -> str:
    texto_conversa = "\n".join(f"{m['role']}: {m['content']}" for m in mensagens)
    r = _provider.chat(
        modelo,
        (
            "Resuma a conversa abaixo em no máximo 2 frases. "
            "Capture o objetivo principal do usuário e decisões tomadas."
        ),
        [{"role": "user", "content": texto_conversa}],
        stream=False, max_tokens=100, temperatura=0.3,
    )
    return r.resposta


def verificar_modelo_disponivel(modelo: str) -> bool:
    return _provider.modelo_disponivel(modelo)


def warmup_modelos(modelos: dict[str, str], keep_alive: str = "10m") -> None:
    _provider.warmup(modelos, keep_alive=keep_alive)
```

- [ ] **Step 4: Run the focused test, then the FULL suite (non-regression gate)**

Run: `.venv/bin/python -m pytest tests/test_llm_fachada.py -v`
Expected: PASS (2 passed).

Run: `.venv/bin/python -m pytest -q`
Expected: baseline da Task 1 + os novos testes, todos verdes. Se algum teste de `test_executor.py` quebrar, verificar se ele mockava `chamar_coordenador`/`chamar_llm` por caminho que mudou; ajustar o mock para `src.core.llm._provider` ou manter o patch no nível de `src.core.llm.chamar_llm` (que continua existindo). NÃO alterar o comportamento, só o ponto de patch se necessário.

- [ ] **Step 5: Commit**

```bash
git add src/core/llm.py tests/test_llm_fachada.py
git commit -m "refactor: core/llm vira fachada sobre a camada de provedores"
```

---

### Task 7: LiteLLMProvider opcional (desligado por padrão)

**Files:**
- Create: `src/provedores/litellm_provider.py`
- Modify: `src/provedores/__init__.py` (tentar importar litellm provider com try/except)
- Modify: `requirements-dev.txt` (extra opcional comentado)
- Test: `tests/test_provedores_litellm.py`

**Interfaces:**
- Consumes: `LLMProvider`, `RespostaLLM` (Task 3); `registry.registrar` (Task 5)
- Produces: `LiteLLMProvider(LLMProvider)` com `nome = "litellm"`, registrado apenas se `litellm` estiver instalado. Import de `litellm` é lazy (dentro dos métodos), nunca no topo do caminho default.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provedores_litellm.py
import sys
from unittest.mock import MagicMock, patch
from src.provedores.litellm_provider import LiteLLMProvider
from src.provedores.base import RespostaLLM


def test_chat_usa_litellm_lazy():
    fake = MagicMock()
    fake.completion.return_value = {
        "choices": [{"message": {"content": "oi litellm"}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2},
    }
    with patch.dict(sys.modules, {"litellm": fake}):
        p = LiteLLMProvider()
        r = p.chat("ollama/qwen3:1.7b", "sys", [{"role": "user", "content": "x"}], stream=False)
    assert isinstance(r, RespostaLLM)
    assert r.resposta == "oi litellm"
    assert r.tokens_entrada == 4
    assert r.tokens_saida == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_provedores_litellm.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.provedores.litellm_provider'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/provedores/litellm_provider.py
"""Provider OPCIONAL via litellm (100+ backends, inclui cloud).

Desligado por padrão. litellm é importado de forma lazy: o módulo carrega
sem a dependência instalada; só falha se alguém chamar de fato o provider.
"""
from __future__ import annotations

import time

from src.provedores.base import LLMProvider, RespostaLLM


class LiteLLMProvider(LLMProvider):
    nome = "litellm"

    def _lib(self):
        import litellm  # lazy: só quando usado
        return litellm

    def chat(
        self,
        modelo: str,
        system_prompt: str,
        mensagens: list[dict],
        *,
        stream: bool = True,
        max_tokens: int = 2048,
        temperatura: float = 0.7,
        num_ctx: int | None = None,
        num_thread: int | None = None,
        keep_alive: str | None = None,
        timeout: float | None = None,
    ) -> RespostaLLM:
        litellm = self._lib()
        msgs = [{"role": "system", "content": system_prompt}, *mensagens]
        inicio = time.time()
        resp = litellm.completion(
            model=modelo,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperatura,
            timeout=timeout,
        )
        texto = resp["choices"][0]["message"]["content"]
        usage = resp.get("usage", {}) or {}
        return RespostaLLM(
            resposta=texto,
            tempo_ms=int((time.time() - inicio) * 1000),
            tokens_entrada=usage.get("prompt_tokens", 0),
            tokens_saida=usage.get("completion_tokens", 0),
        )

    def modelo_disponivel(self, modelo: str) -> bool:
        # litellm não tem inventário local; assume-se configurado externamente.
        return True

    def warmup(self, modelos: dict[str, str], keep_alive: str = "10m") -> None:
        return None


try:  # registro só se quisermos disponibilizar mesmo sem litellm instalado
    from src.provedores import registry as _registry

    _registry.registrar("litellm", LiteLLMProvider)
except Exception:
    pass
```

Atualizar `src/provedores/__init__.py`:

```python
# src/provedores/__init__.py
"""Camada de abstração de provedores de LLM."""
from src.provedores import ollama_provider  # noqa: F401  (auto-registra "ollama")

try:
    from src.provedores import litellm_provider  # noqa: F401  (registra "litellm" se possível)
except Exception:
    pass
```

Adicionar ao fim de `requirements-dev.txt`:

```
# Opcional: provider litellm (desligado por padrão; instale só se for usar)
# litellm>=1.0,<2.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_provedores_litellm.py -v`
Expected: PASS (1 passed). O teste injeta um `litellm` falso via `sys.modules`, então passa mesmo sem a lib instalada.

- [ ] **Step 5: Commit**

```bash
git add src/provedores/litellm_provider.py src/provedores/__init__.py requirements-dev.txt tests/test_provedores_litellm.py
git commit -m "feat: LiteLLMProvider opcional com import lazy"
```

---

### Task 8: conexoes/bus.py (tipos + MessageBus assíncrono)

**Files:**
- Create: `src/conexoes/__init__.py`
- Create: `src/conexoes/bus.py`
- Test: `tests/test_conexoes_bus.py`

**Interfaces:**
- Consumes: nada
- Produces:
  - `SenderInfo` (dataclass frozen): `id: str`, `nome: str = ""`, `canal: str = ""`
  - `InboundMessage` (dataclass frozen): `texto: str`, `sender: SenderInfo`, `canal: str`, `chat_id: str`, `metadata: dict = {}`
  - `OutboundMessage` (dataclass frozen): `texto: str`, `canal: str`, `chat_id: str`, `metadata: dict = {}`
  - `MessageBus` com `async publicar_entrada(msg)`, `async proxima_entrada() -> InboundMessage`, `assinar_saida(callback)`, `async publicar_saida(msg)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_conexoes_bus.py
import asyncio
from src.conexoes.bus import MessageBus, InboundMessage, OutboundMessage, SenderInfo


def test_inbound_roundtrip():
    async def cenario():
        bus = MessageBus()
        msg = InboundMessage(
            texto="oi", sender=SenderInfo(id="u1", nome="Nik"),
            canal="cli", chat_id="c1",
        )
        await bus.publicar_entrada(msg)
        recebida = await bus.proxima_entrada()
        return recebida

    recebida = asyncio.run(cenario())
    assert recebida.texto == "oi"
    assert recebida.sender.id == "u1"
    assert recebida.canal == "cli"


def test_saida_notifica_assinantes():
    async def cenario():
        bus = MessageBus()
        recebidas = []

        async def consumidor(m: OutboundMessage):
            recebidas.append(m)

        bus.assinar_saida(consumidor)
        await bus.publicar_saida(OutboundMessage(texto="pong", canal="cli", chat_id="c1"))
        return recebidas

    recebidas = asyncio.run(cenario())
    assert len(recebidas) == 1
    assert recebidas[0].texto == "pong"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_conexoes_bus.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.conexoes'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/conexoes/__init__.py
"""Camada de conexões: bus + canais (offline-first, opt-in)."""
```

```python
# src/conexoes/bus.py
"""Barramento de mensagens assíncrono e leve (asyncio, sem broker externo)."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SenderInfo:
    id: str
    nome: str = ""
    canal: str = ""


@dataclass(frozen=True)
class InboundMessage:
    texto: str
    sender: SenderInfo
    canal: str
    chat_id: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class OutboundMessage:
    texto: str
    canal: str
    chat_id: str
    metadata: dict = field(default_factory=dict)


SaidaCallback = Callable[[OutboundMessage], Awaitable[None]]


class MessageBus:
    """Entrada via fila (1 consumidor: o coordenador). Saída via pub/sub (N canais)."""

    def __init__(self) -> None:
        self._entrada: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._assinantes_saida: list[SaidaCallback] = []

    async def publicar_entrada(self, msg: InboundMessage) -> None:
        await self._entrada.put(msg)

    async def proxima_entrada(self) -> InboundMessage:
        return await self._entrada.get()

    def assinar_saida(self, callback: SaidaCallback) -> None:
        self._assinantes_saida.append(callback)

    async def publicar_saida(self, msg: OutboundMessage) -> None:
        for cb in self._assinantes_saida:
            await cb(msg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_conexoes_bus.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/conexoes/__init__.py src/conexoes/bus.py tests/test_conexoes_bus.py
git commit -m "feat: MessageBus assíncrono e tipos de mensagem"
```

---

## Fechamento da Fase 1

- [ ] **Gate final de não-regressão**

Run: `.venv/bin/python -m pytest -q`
Expected: baseline (111) + novos testes (base 2, ollama 3, registry 3, fachada 2, litellm 1, bus 2 = 13) todos verdes.

- [ ] **Lint das camadas novas**

Run: `.venv/bin/ruff check src/provedores src/conexoes tests`
Expected: limpo.

- [ ] **Resumo do estado**

Após a Fase 1: existe abstração de provider (Ollama default, litellm opcional), um message bus assíncrono e CI. O core segue intacto e os agentes não mudaram. Pronto para a Fase 2 (hub de canais), que consome `MessageBus` e adiciona `BaseChannel`/`ChannelManager`/Telegram.

## Self-Review (preenchido)

- **Spec coverage:** abstração de provider (Tasks 3-7), bus (Task 8), CI (Task 2), sync do fork (Task 1), não-regressão (gates nas Tasks 1, 6 e fechamento). Itens do spec referentes a canais/MCP/skills/sessão são Fases 2-4, fora deste plano por decomposição.
- **Placeholder scan:** sem TBD/TODO; todo step com código real e comando com saída esperada.
- **Type consistency:** `RespostaLLM` (campos resposta/tempo_ms/tokens_entrada/tokens_saida) usada igual nas Tasks 3,4,6,7. `registrar/criar/disponiveis` idênticos nas Tasks 5,6,7. `MessageBus`/`InboundMessage`/`OutboundMessage`/`SenderInfo` consistentes na Task 8.
