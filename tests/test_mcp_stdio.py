import io
import json
from unittest.mock import patch

from src.extensoes.mcp.stdio import StdioTransport


class FakeProc:
    def __init__(self, resposta: dict):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(json.dumps(resposta) + "\n")
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return None


@patch("src.extensoes.mcp.stdio.subprocess.Popen")
def test_start_herda_stderr_sem_criar_pipe(mock_popen):
    t = StdioTransport(["servidor-mcp"])

    t.start()

    assert mock_popen.call_args.kwargs["stderr"] is None


def test_request_encoda_e_decoda():
    t = StdioTransport(["echo"])
    t._proc = FakeProc({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
    resp = t.request({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
    assert resp["result"] == {"ok": True}
    enviado = t._proc.stdin.getvalue().strip()
    assert json.loads(enviado)["method"] == "ping"


def test_request_detecta_eof():
    t = StdioTransport(["echo"])
    t._proc = FakeProc({})
    t._proc.stdout = io.StringIO("")

    try:
        t.request({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    except RuntimeError as exc:
        assert "sem enviar resposta" in str(exc)
    else:
        raise AssertionError("EOF deveria gerar erro")


def test_notify_envia_sem_aguardar_resposta():
    t = StdioTransport(["echo"])
    t._proc = FakeProc({})

    t.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})

    enviado = json.loads(t._proc.stdin.getvalue().strip())
    assert enviado["method"] == "notifications/initialized"
