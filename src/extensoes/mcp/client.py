"""Cliente MCP: JSON-RPC 2.0 sobre um Transport injetavel."""
from __future__ import annotations

from typing import Protocol


class MCPError(Exception):
    pass


class Transport(Protocol):
    def request(self, payload: dict) -> dict: ...
    def notify(self, payload: dict) -> None: ...


class MCPClient:
    def __init__(
        self,
        transport: Transport,
        *,
        client_name: str = "potato-claw",
        client_version: str = "1.0.0",
    ) -> None:
        self._transport = transport
        self._id = 0
        self._client_name = client_name
        self._client_version = client_version

    def _rpc(self, metodo: str, params: dict | None = None) -> dict:
        self._id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": metodo,
            "params": params or {},
        }
        resp = self._transport.request(payload)
        if "error" in resp:
            raise MCPError(str(resp["error"]))
        return resp.get("result", {})

    def _notify(self, metodo: str, params: dict | None = None) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": metodo,
        }
        if params is not None:
            payload["params"] = params
        self._transport.notify(payload)

    def initialize(self) -> dict:
        resultado = self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": self._client_name,
                    "version": self._client_version,
                },
            },
        )
        self._notify("notifications/initialized")
        return resultado

    def list_tools(self) -> list[dict]:
        return self._rpc("tools/list").get("tools", [])

    def call_tool(self, nome: str, argumentos: dict) -> dict:
        return self._rpc("tools/call", {"name": nome, "arguments": argumentos})
