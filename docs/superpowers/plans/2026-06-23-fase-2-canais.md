# Fase 2 - Hub de canais Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) ou superpowers:executing-plans. Steps usam checkbox (`- [ ]`).

**Goal:** Adicionar um hub de canais sobre o `MessageBus` da Fase 1: `BaseChannel` (ABC), `ChannelManager` (retry/backoff/split + allow-list), registry de canais, um Runtime que liga o bus ao `SistemaAgentes`, o CLI como canal e o Telegram (long-polling) como 1º canal externo.

**Architecture:** Canais publicam `InboundMessage` no bus; o `Runtime` consome, chama `SistemaAgentes.executar` (em thread, pois é síncrono) e publica `OutboundMessage`; o `ChannelManager` assina a saída e entrega ao canal de origem com retry/split. Tudo opt-in: sem canal configurado, o `main.py` atual segue funcionando.

**Tech Stack:** Python 3.11+, asyncio, urllib (stdlib, para Telegram, sem dep nova), pytest. Reusa `src/conexoes/bus.py`.

## Global Constraints

- Python 3.11+. Offline-first: o Telegram é opt-in; nenhuma dep nova (urllib stdlib).
- Não-regressão é gate: baseline atual de 178 testes continua verde.
- PC fraco: canais são lazy; `SistemaAgentes` roda em `asyncio.to_thread` para não travar o loop.
- `SistemaAgentes` tem assinatura `__init__(memoria=None, cache=None, semantica=None)` e `executar(nome_agente: str, pergunta: str) -> str`.
- Tipos do bus (Fase 1): `InboundMessage(texto, sender, canal, chat_id, metadata)`, `OutboundMessage(texto, canal, chat_id, metadata)`, `SenderInfo(id, nome, canal)`, `MessageBus` com `publicar_entrada/proxima_entrada/assinar_saida/publicar_saida`.
- pt-BR com acentos nos textos visíveis. Sem em dashes. Sem Co-Authored-By.
- Comandos de teste: `.venv/bin/python -m pytest ... -v`.

## File Structure

```
src/conexoes/
  channels/
    __init__.py     registry import dos canais built-in
    base.py         BaseChannel (ABC) + allow-list
    manager.py      ChannelManager (retry/backoff/split, assina saída do bus)
    registry.py     factories de canal (nome -> factory)
    cli.py          CLIChannel
    telegram.py     TelegramChannel (long-polling via urllib)
  runtime.py        Runtime: liga bus -> SistemaAgentes -> bus
```

---

### Task 1: BaseChannel (ABC) + allow-list

**Files:**
- Create: `src/conexoes/channels/__init__.py`
- Create: `src/conexoes/channels/base.py`
- Test: `tests/test_channels_base.py`

**Interfaces:**
- Consumes: `MessageBus`, `OutboundMessage`, `SenderInfo` (Fase 1)
- Produces: `BaseChannel(ABC)`:
  - `__init__(self, bus: MessageBus, *, nome: str, allow_list: list[str] | None = None, max_message_length: int = 0)`
  - `nome -> str` (property)
  - abstratos `async start()`, `async stop()`, `async send(msg: OutboundMessage)`
  - `is_allowed_sender(self, sender: SenderInfo) -> bool` (allow_list vazia = libera todos)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_channels_base.py
import pytest
from src.conexoes.bus import MessageBus, SenderInfo, OutboundMessage
from src.conexoes.channels.base import BaseChannel


class CanalDummy(BaseChannel):
    async def start(self):  # noqa: D102
        self._iniciado = True

    async def stop(self):  # noqa: D102
        self._iniciado = False

    async def send(self, msg: OutboundMessage):  # noqa: D102
        self.enviadas = getattr(self, "enviadas", [])
        self.enviadas.append(msg)


def test_base_channel_nao_instancia():
    with pytest.raises(TypeError):
        BaseChannel(MessageBus(), nome="x")


def test_allow_list_vazia_libera_todos():
    c = CanalDummy(MessageBus(), nome="dummy")
    assert c.is_allowed_sender(SenderInfo(id="qualquer")) is True


def test_allow_list_restringe():
    c = CanalDummy(MessageBus(), nome="dummy", allow_list=["u1"])
    assert c.is_allowed_sender(SenderInfo(id="u1")) is True
    assert c.is_allowed_sender(SenderInfo(id="u2")) is False


def test_nome_exposto():
    c = CanalDummy(MessageBus(), nome="dummy")
    assert c.nome == "dummy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_channels_base.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.conexoes.channels'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/conexoes/channels/__init__.py
"""Hub de canais (offline-first, opt-in)."""
```

```python
# src/conexoes/channels/base.py
"""Contrato comum de um canal de mensageria."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.conexoes.bus import MessageBus, OutboundMessage, SenderInfo


class BaseChannel(ABC):
    def __init__(
        self,
        bus: MessageBus,
        *,
        nome: str,
        allow_list: list[str] | None = None,
        max_message_length: int = 0,
    ) -> None:
        self._bus = bus
        self._nome = nome
        self._allow_list = list(allow_list or [])
        self.max_message_length = max_message_length

    @property
    def nome(self) -> str:
        return self._nome

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        ...

    def is_allowed_sender(self, sender: SenderInfo) -> bool:
        if not self._allow_list:
            return True
        return sender.id in self._allow_list
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_channels_base.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/conexoes/channels/__init__.py src/conexoes/channels/base.py tests/test_channels_base.py
git commit -m "feat: BaseChannel com allow-list"
```

---

### Task 2: ChannelManager (retry/backoff/split + assinatura da saída)

**Files:**
- Create: `src/conexoes/channels/manager.py`
- Test: `tests/test_channels_manager.py`

**Interfaces:**
- Consumes: `BaseChannel` (Task 1), `MessageBus`, `OutboundMessage`
- Produces: `ChannelManager`:
  - `__init__(self, bus: MessageBus)`
  - `adicionar(self, canal: BaseChannel) -> None`
  - `async iniciar_todos() -> None` / `async parar_todos() -> None`
  - `async entregar(self, msg: OutboundMessage, *, max_retries: int = 3, base_delay: float = 0.01) -> bool` (roteia por `msg.canal`, retry com backoff exponencial, split por `max_message_length`)
  - assina `bus.publicar_saida` via `bus.assinar_saida(self.entregar)` no `__init__`
  - `_split(self, texto: str, limite: int) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_channels_manager.py
import asyncio
import pytest
from src.conexoes.bus import MessageBus, OutboundMessage
from src.conexoes.channels.base import BaseChannel
from src.conexoes.channels.manager import ChannelManager


class CanalFalho(BaseChannel):
    def __init__(self, bus, *, nome, falhas=0, max_message_length=0):
        super().__init__(bus, nome=nome, max_message_length=max_message_length)
        self.falhas_restantes = falhas
        self.enviadas = []

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, msg):
        if self.falhas_restantes > 0:
            self.falhas_restantes -= 1
            raise RuntimeError("falha temporaria")
        self.enviadas.append(msg.texto)


def test_entrega_simples():
    async def cenario():
        bus = MessageBus()
        mgr = ChannelManager(bus)
        canal = CanalFalho(bus, nome="cli")
        mgr.adicionar(canal)
        ok = await mgr.entregar(OutboundMessage(texto="oi", canal="cli", chat_id="c1"))
        return ok, canal.enviadas

    ok, enviadas = asyncio.run(cenario())
    assert ok is True
    assert enviadas == ["oi"]


def test_retry_recupera_apos_falhas():
    async def cenario():
        bus = MessageBus()
        mgr = ChannelManager(bus)
        canal = CanalFalho(bus, nome="cli", falhas=2)
        mgr.adicionar(canal)
        ok = await mgr.entregar(
            OutboundMessage(texto="oi", canal="cli", chat_id="c1"),
            max_retries=3, base_delay=0.0,
        )
        return ok, canal.enviadas

    ok, enviadas = asyncio.run(cenario())
    assert ok is True
    assert enviadas == ["oi"]


def test_split_mensagem_longa():
    async def cenario():
        bus = MessageBus()
        mgr = ChannelManager(bus)
        canal = CanalFalho(bus, nome="cli", max_message_length=5)
        mgr.adicionar(canal)
        await mgr.entregar(OutboundMessage(texto="abcdefghij", canal="cli", chat_id="c1"))
        return canal.enviadas

    enviadas = asyncio.run(cenario())
    assert enviadas == ["abcde", "fghij"]


def test_canal_inexistente_retorna_false():
    async def cenario():
        bus = MessageBus()
        mgr = ChannelManager(bus)
        return await mgr.entregar(OutboundMessage(texto="x", canal="nao-existe", chat_id="c"))

    assert asyncio.run(cenario()) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_channels_manager.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.conexoes.channels.manager'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/conexoes/channels/manager.py
"""Gerencia canais e entrega de saída com retry/backoff e split."""
from __future__ import annotations

import asyncio

from src.conexoes.bus import MessageBus, OutboundMessage
from src.conexoes.channels.base import BaseChannel


class ChannelManager:
    def __init__(self, bus: MessageBus) -> None:
        self._bus = bus
        self._canais: dict[str, BaseChannel] = {}
        bus.assinar_saida(self.entregar)

    def adicionar(self, canal: BaseChannel) -> None:
        self._canais[canal.nome] = canal

    async def iniciar_todos(self) -> None:
        for canal in self._canais.values():
            await canal.start()

    async def parar_todos(self) -> None:
        for canal in self._canais.values():
            await canal.stop()

    def _split(self, texto: str, limite: int) -> list[str]:
        if limite <= 0 or len(texto) <= limite:
            return [texto]
        return [texto[i:i + limite] for i in range(0, len(texto), limite)]

    async def entregar(
        self,
        msg: OutboundMessage,
        *,
        max_retries: int = 3,
        base_delay: float = 0.01,
    ) -> bool:
        canal = self._canais.get(msg.canal)
        if canal is None:
            return False

        partes = self._split(msg.texto, canal.max_message_length)
        for parte in partes:
            sub = OutboundMessage(
                texto=parte, canal=msg.canal, chat_id=msg.chat_id, metadata=msg.metadata
            )
            entregue = False
            for tentativa in range(max_retries):
                try:
                    await canal.send(sub)
                    entregue = True
                    break
                except Exception:
                    if tentativa < max_retries - 1:
                        await asyncio.sleep(base_delay * (2 ** tentativa))
            if not entregue:
                return False
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_channels_manager.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/conexoes/channels/manager.py tests/test_channels_manager.py
git commit -m "feat: ChannelManager com retry/backoff e split"
```

---

### Task 3: Registry de canais

**Files:**
- Create: `src/conexoes/channels/registry.py`
- Test: `tests/test_channels_registry.py`

**Interfaces:**
- Consumes: `BaseChannel`, `MessageBus`
- Produces:
  - `ChannelFactory = Callable[[MessageBus, dict], BaseChannel]`
  - `registrar(nome: str, factory) -> None`
  - `criar(nome: str, bus: MessageBus, config: dict) -> BaseChannel`
  - `disponiveis() -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_channels_registry.py
import pytest
from src.conexoes.bus import MessageBus, OutboundMessage
from src.conexoes.channels.base import BaseChannel
from src.conexoes.channels import registry


class _Falso(BaseChannel):
    async def start(self): ...
    async def stop(self): ...
    async def send(self, msg: OutboundMessage): ...


def test_registrar_e_criar():
    registry.registrar("falso", lambda bus, cfg: _Falso(bus, nome="falso"))
    c = registry.criar("falso", MessageBus(), {})
    assert isinstance(c, _Falso)
    assert "falso" in registry.disponiveis()


def test_criar_invalido_levanta():
    with pytest.raises(ValueError):
        registry.criar("inexistente", MessageBus(), {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_channels_registry.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.conexoes.channels.registry'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/conexoes/channels/registry.py
"""Registro de factories de canal."""
from __future__ import annotations

from collections.abc import Callable

from src.conexoes.bus import MessageBus
from src.conexoes.channels.base import BaseChannel

ChannelFactory = Callable[[MessageBus, dict], BaseChannel]

_factories: dict[str, ChannelFactory] = {}


def registrar(nome: str, factory: ChannelFactory) -> None:
    _factories[nome] = factory


def criar(nome: str, bus: MessageBus, config: dict) -> BaseChannel:
    if nome not in _factories:
        raise ValueError(f"Canal '{nome}' nao registrado. Disponiveis: {list(_factories)}")
    return _factories[nome](bus, config)


def disponiveis() -> list[str]:
    return list(_factories)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_channels_registry.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/conexoes/channels/registry.py tests/test_channels_registry.py
git commit -m "feat: registry de canais"
```

---

### Task 4: Runtime (bus -> SistemaAgentes -> bus)

**Files:**
- Create: `src/conexoes/runtime.py`
- Test: `tests/test_runtime.py`

**Interfaces:**
- Consumes: `MessageBus`, `InboundMessage`, `OutboundMessage`
- Produces: `Runtime`:
  - `__init__(self, bus: MessageBus, processar)` onde `processar` é `Callable[[str, str], str]` com assinatura `(nome_agente, pergunta) -> resposta` (default: liga em `SistemaAgentes.executar`)
  - `async processar_uma(self, msg: InboundMessage) -> OutboundMessage` (chama `processar` via `asyncio.to_thread`, publica saída)
  - `async rodar(self) -> None` (loop infinito consumindo `proxima_entrada`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runtime.py
import asyncio
from src.conexoes.bus import MessageBus, InboundMessage, OutboundMessage, SenderInfo
from src.conexoes.runtime import Runtime


def test_processar_uma_gera_outbound():
    async def cenario():
        bus = MessageBus()
        recebidas = []

        async def coletor(m: OutboundMessage):
            recebidas.append(m)

        bus.assinar_saida(coletor)

        def processar(agente, pergunta):
            return f"eco: {pergunta}"

        rt = Runtime(bus, processar)
        msg = InboundMessage(
            texto="oi", sender=SenderInfo(id="u1"), canal="cli", chat_id="c1"
        )
        out = await rt.processar_uma(msg)
        return out, recebidas

    out, recebidas = asyncio.run(cenario())
    assert out.texto == "eco: oi"
    assert out.canal == "cli"
    assert out.chat_id == "c1"
    assert len(recebidas) == 1
    assert recebidas[0].texto == "eco: oi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_runtime.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.conexoes.runtime'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/conexoes/runtime.py
"""Liga o bus ao motor de agentes: inbound -> resposta -> outbound."""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from src.conexoes.bus import InboundMessage, MessageBus, OutboundMessage

Processador = Callable[[str, str], str]


def _processador_padrao() -> Processador:
    # Import tardio: evita carregar o motor (e Ollama) quando não há canais.
    from src.agentes.executor import SistemaAgentes

    sistema = SistemaAgentes()

    def processar(nome_agente: str, pergunta: str) -> str:
        return sistema.executar(nome_agente, pergunta)

    return processar


class Runtime:
    def __init__(self, bus: MessageBus, processar: Processador | None = None) -> None:
        self._bus = bus
        self._processar = processar or _processador_padrao()
        self.agente_padrao = "generalista"

    async def processar_uma(self, msg: InboundMessage) -> OutboundMessage:
        resposta = await asyncio.to_thread(self._processar, self.agente_padrao, msg.texto)
        out = OutboundMessage(texto=resposta, canal=msg.canal, chat_id=msg.chat_id)
        await self._bus.publicar_saida(out)
        return out

    async def rodar(self) -> None:
        while True:
            msg = await self._bus.proxima_entrada()
            await self.processar_uma(msg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_runtime.py -v`
Expected: PASS (1 passed). O teste injeta `processar`, então não carrega `SistemaAgentes`/Ollama.

- [ ] **Step 5: Commit**

```bash
git add src/conexoes/runtime.py tests/test_runtime.py
git commit -m "feat: Runtime liga bus ao motor de agentes"
```

---

### Task 5: CLIChannel

**Files:**
- Create: `src/conexoes/channels/cli.py`
- Test: `tests/test_channels_cli.py`

**Interfaces:**
- Consumes: `BaseChannel`, `MessageBus`, `InboundMessage`, `OutboundMessage`, `SenderInfo`
- Produces: `CLIChannel(BaseChannel)`:
  - `async receber(self, texto: str) -> None` (publica `InboundMessage` no bus, canal="cli", sender id="local")
  - `async send(self, msg: OutboundMessage) -> None` (registra em `self.saidas` e imprime)
  - `start`/`stop` no-op
  - factory registrada como "cli"

- [ ] **Step 1: Write the failing test**

```python
# tests/test_channels_cli.py
import asyncio
from src.conexoes.bus import MessageBus, OutboundMessage
from src.conexoes.channels.cli import CLIChannel


def test_receber_publica_inbound():
    async def cenario():
        bus = MessageBus()
        canal = CLIChannel(bus, nome="cli")
        await canal.receber("ola mundo")
        msg = await bus.proxima_entrada()
        return msg

    msg = asyncio.run(cenario())
    assert msg.texto == "ola mundo"
    assert msg.canal == "cli"


def test_send_registra_saida():
    async def cenario():
        bus = MessageBus()
        canal = CLIChannel(bus, nome="cli")
        await canal.send(OutboundMessage(texto="resposta", canal="cli", chat_id="local"))
        return canal.saidas

    saidas = asyncio.run(cenario())
    assert saidas == ["resposta"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_channels_cli.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.conexoes.channels.cli'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/conexoes/channels/cli.py
"""Canal CLI: stdin vira inbound, resposta sai no console."""
from __future__ import annotations

from rich.console import Console

from src.conexoes.bus import InboundMessage, MessageBus, OutboundMessage, SenderInfo
from src.conexoes.channels.base import BaseChannel
from src.conexoes.channels.registry import registrar

console = Console()


class CLIChannel(BaseChannel):
    def __init__(self, bus: MessageBus, *, nome: str = "cli", allow_list=None) -> None:
        super().__init__(bus, nome=nome, allow_list=allow_list)
        self.saidas: list[str] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def receber(self, texto: str) -> None:
        msg = InboundMessage(
            texto=texto,
            sender=SenderInfo(id="local", nome="local", canal=self.nome),
            canal=self.nome,
            chat_id="local",
        )
        await self._bus.publicar_entrada(msg)

    async def send(self, msg: OutboundMessage) -> None:
        self.saidas.append(msg.texto)
        console.print(msg.texto)


registrar("cli", lambda bus, cfg: CLIChannel(bus, allow_list=cfg.get("allow_list")))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_channels_cli.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/conexoes/channels/cli.py tests/test_channels_cli.py
git commit -m "feat: CLIChannel (CLI como canal no bus)"
```

---

### Task 6: TelegramChannel (long-polling via urllib)

**Files:**
- Create: `src/conexoes/channels/telegram.py`
- Modify: `src/conexoes/channels/__init__.py` (importar cli e telegram para auto-registro)
- Test: `tests/test_channels_telegram.py`

**Interfaces:**
- Consumes: `BaseChannel`, `MessageBus`, `InboundMessage`, `OutboundMessage`, `SenderInfo`
- Produces: `TelegramChannel(BaseChannel)`:
  - `__init__(self, bus, *, token: str, nome="telegram", allow_list=None, max_message_length=4096)`
  - `_api_call(self, metodo: str, params: dict) -> dict` (HTTP via urllib; isolado para mock)
  - `async send(self, msg)` (chama sendMessage via `asyncio.to_thread`)
  - `_inbound_de_update(self, update: dict) -> InboundMessage | None` (parse de update do Telegram; respeita allow-list)
  - `start`/`stop` controlam o loop de polling (não exercitado nos testes unitários)
  - factory registrada como "telegram" (lê token de `cfg["token"]`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_channels_telegram.py
import asyncio
from unittest.mock import patch
from src.conexoes.bus import MessageBus, OutboundMessage
from src.conexoes.channels.telegram import TelegramChannel


def test_parse_update_vira_inbound():
    bus = MessageBus()
    canal = TelegramChannel(bus, token="t")
    update = {
        "message": {
            "text": "oi bot",
            "chat": {"id": 123},
            "from": {"id": 99, "first_name": "Nik"},
        }
    }
    msg = canal._inbound_de_update(update)
    assert msg is not None
    assert msg.texto == "oi bot"
    assert msg.chat_id == "123"
    assert msg.sender.id == "99"
    assert msg.canal == "telegram"


def test_allow_list_bloqueia_update():
    bus = MessageBus()
    canal = TelegramChannel(bus, token="t", allow_list=["1"])
    update = {"message": {"text": "x", "chat": {"id": 5}, "from": {"id": 99}}}
    assert canal._inbound_de_update(update) is None


def test_send_chama_sendmessage():
    async def cenario():
        bus = MessageBus()
        canal = TelegramChannel(bus, token="t")
        with patch.object(canal, "_api_call", return_value={"ok": True}) as mock_api:
            await canal.send(OutboundMessage(texto="oi", canal="telegram", chat_id="123"))
        return mock_api

    mock_api = asyncio.run(cenario())
    metodo, params = mock_api.call_args[0]
    assert metodo == "sendMessage"
    assert params["chat_id"] == "123"
    assert params["text"] == "oi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_channels_telegram.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.conexoes.channels.telegram'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/conexoes/channels/telegram.py
"""Canal Telegram via Bot API (long-polling), sem dependência externa (urllib)."""
from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request

from src.conexoes.bus import InboundMessage, MessageBus, OutboundMessage, SenderInfo
from src.conexoes.channels.base import BaseChannel
from src.conexoes.channels.registry import registrar

_API = "https://api.telegram.org/bot{token}/{metodo}"


class TelegramChannel(BaseChannel):
    def __init__(
        self,
        bus: MessageBus,
        *,
        token: str,
        nome: str = "telegram",
        allow_list=None,
        max_message_length: int = 4096,
    ) -> None:
        super().__init__(bus, nome=nome, allow_list=allow_list,
                         max_message_length=max_message_length)
        self._token = token
        self._rodando = False
        self._offset = 0

    def _api_call(self, metodo: str, params: dict) -> dict:
        url = _API.format(token=self._token, metodo=metodo)
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(url, data=data, timeout=65) as resp:
            return json.loads(resp.read().decode())

    def _inbound_de_update(self, update: dict) -> InboundMessage | None:
        msg = update.get("message") or {}
        texto = msg.get("text")
        if not texto:
            return None
        remetente = msg.get("from", {})
        sender = SenderInfo(
            id=str(remetente.get("id", "")),
            nome=remetente.get("first_name", ""),
            canal=self.nome,
        )
        if not self.is_allowed_sender(sender):
            return None
        return InboundMessage(
            texto=texto,
            sender=sender,
            canal=self.nome,
            chat_id=str(msg.get("chat", {}).get("id", "")),
        )

    async def send(self, msg: OutboundMessage) -> None:
        await asyncio.to_thread(
            self._api_call, "sendMessage", {"chat_id": msg.chat_id, "text": msg.texto}
        )

    async def start(self) -> None:
        self._rodando = True
        while self._rodando:
            resp = await asyncio.to_thread(
                self._api_call, "getUpdates", {"offset": self._offset, "timeout": 60}
            )
            for update in resp.get("result", []):
                self._offset = update["update_id"] + 1
                inbound = self._inbound_de_update(update)
                if inbound is not None:
                    await self._bus.publicar_entrada(inbound)

    async def stop(self) -> None:
        self._rodando = False


registrar("telegram", lambda bus, cfg: TelegramChannel(
    bus, token=cfg["token"], allow_list=cfg.get("allow_list")
))
```

Atualizar `src/conexoes/channels/__init__.py`:

```python
# src/conexoes/channels/__init__.py
"""Hub de canais (offline-first, opt-in)."""
from src.conexoes.channels import cli  # noqa: F401  (registra "cli")
from src.conexoes.channels import telegram  # noqa: F401  (registra "telegram")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_channels_telegram.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/conexoes/channels/telegram.py src/conexoes/channels/__init__.py tests/test_channels_telegram.py
git commit -m "feat: TelegramChannel via long-polling (urllib, sem dep nova)"
```

---

## Fechamento da Fase 2

- [ ] **Gate final de não-regressão**

Run: `.venv/bin/python -m pytest -q`
Expected: baseline (178) + novos (base 4, manager 4, registry 2, runtime 1, cli 2, telegram 3 = 16) = 194 verdes.

- [ ] **Lint das camadas novas**

Run: `.venv/bin/ruff check src/conexoes`
Expected: limpo (corrigir com `--fix` se acusar imports).

- [ ] **Resumo do estado**

Após a Fase 2: hub de canais funcional sobre o bus. CLI e Telegram como canais; `ChannelManager` com retry/split; `Runtime` ligando ao `SistemaAgentes`. Próximo: Fase 3 (skills pasta/markdown + MCP).

Nota: integrar o hub ao `main.py` (modo "servidor de canais") e o token do Telegram via config/env ficam para uma tarefa de integração no fim da Fase 2 ou início da Fase 3, quando o Nikolas for ligar um bot real. Os testes desta fase não exigem rede nem token.

## Self-Review (preenchido)

- **Spec coverage:** hub de canais (Tasks 1-3,5,6), integração bus-agentes (Task 4), Telegram 1º canal (Task 6), CLI como canal (Task 5), allow-list (Task 1), retry/split (Task 2). MCP/skills/sessão são Fases 3-4.
- **Placeholder scan:** sem TBD/TODO; todo step com código real e comando com saída esperada.
- **Type consistency:** `BaseChannel(bus, *, nome, allow_list, max_message_length)` e `send(OutboundMessage)` usados igual nas Tasks 1,2,5,6. `ChannelManager.entregar` assinatura idêntica. `registrar/criar/disponiveis` idênticos nas Tasks 3,5,6. `Runtime(bus, processar)` consistente.
