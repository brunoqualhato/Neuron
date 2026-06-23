"""Cliente MCP: JSON-RPC 2.0 sobre um Transport injetavel."""
from __future__ import annotations

from typing import Protocol


class MCPError(Exception):
    pass


class Transport(Protocol):
    def request(self, payload: dict) -> dict: ...


class MCPClient:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self._id = 0

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

    def initialize(self) -> dict:
        return self._rpc(
            "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}}
        )

    def list_tools(self) -> list[dict]:
        return self._rpc("tools/list").get("tools", [])

    def call_tool(self, nome: str, argumentos: dict) -> dict:
        return self._rpc("tools/call", {"name": nome, "arguments": argumentos})
