"""Transporte stdio para servidores MCP locais (subprocess)."""
from __future__ import annotations

import json
import subprocess


class StdioTransport:
    def __init__(self, comando: list[str]) -> None:
        self._comando = comando
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        self._proc = subprocess.Popen(
            self._comando,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def request(self, payload: dict) -> dict:
        if self._proc is None:
            raise RuntimeError("Transport nao iniciado. Chame start().")
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()
        linha = self._proc.stdout.readline()
        return json.loads(linha)

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            self._proc.wait(timeout=5)
            self._proc = None
