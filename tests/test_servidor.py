import asyncio

from src.conexoes import servidor
from src.core import config


def test_canais_configurados_vazio(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert config.canais_configurados() == []


def test_canais_configurados_telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_ALLOW_LIST", "111, 222")
    cfgs = config.canais_configurados()
    assert len(cfgs) == 1
    assert cfgs[0]["tipo"] == "telegram"
    assert cfgs[0]["token"] == "tok123"
    assert cfgs[0]["allow_list"] == ["111", "222"]


def test_montar_servidor_sem_canais(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    _, _, canais = servidor.montar_servidor(processar=lambda a, t: t)
    assert canais == []


def test_montar_servidor_com_telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    _, _, canais = servidor.montar_servidor(processar=lambda a, t: t)
    assert len(canais) == 1
    assert canais[0].nome == "telegram"


def test_servir_encerra_runtime_quando_canal_para(monkeypatch):
    class CanalQueEncerra:
        nome = "telegram"

        async def start(self):
            return None

    class RuntimeInfinito:
        cancelado = False

        async def rodar(self):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelado = True
                raise

    class Manager:
        parado = False

        async def parar_todos(self):
            self.parado = True

    canal = CanalQueEncerra()
    runtime = RuntimeInfinito()
    manager = Manager()
    monkeypatch.setattr(servidor, "canais_configurados", lambda: [{"tipo": "telegram"}])
    monkeypatch.setattr(
        servidor,
        "montar_servidor",
        lambda processar=None: (manager, runtime, [canal]),
    )

    asyncio.run(asyncio.wait_for(servidor.servir(), timeout=0.5))

    assert runtime.cancelado is True
    assert manager.parado is True
