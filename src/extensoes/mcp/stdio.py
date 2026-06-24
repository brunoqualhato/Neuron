"""Transporte stdio para servidores MCP locais (subprocess)."""
from __future__ import annotations

import json
import select
import subprocess


class StdioTransport:
    def __init__(self, comando: list[str], timeout_s: float = 30.0) -> None:
        self._comando = comando
        self._timeout_s = timeout_s
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        self._proc = subprocess.Popen(
            self._comando,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def _write(self, payload: dict) -> None:
        if self._proc is None:
            raise RuntimeError("Transport nao iniciado. Chame start().")
        if self._proc.poll() is not None:
            raise RuntimeError("Servidor MCP encerrou antes da requisição.")
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def notify(self, payload: dict) -> None:
        self._write(payload)

    def request(self, payload: dict) -> dict:
        self._write(payload)
        pode_aguardar = True
        try:
            self._proc.stdout.fileno()
        except (AttributeError, OSError, TypeError, ValueError):
            pode_aguardar = False
        if pode_aguardar:
            prontos, _, _ = select.select(
                [self._proc.stdout],
                [],
                [],
                self._timeout_s,
            )
            if not prontos:
                raise TimeoutError(
                    f"Servidor MCP não respondeu em {self._timeout_s:g}s."
                )
        linha = self._proc.stdout.readline()
        if not linha:
            raise RuntimeError("Servidor MCP encerrou sem enviar resposta.")
        return json.loads(linha)

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
            self._proc = None
