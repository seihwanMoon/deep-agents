"""MCP remote/local tool runner used by Tools API endpoints."""

from __future__ import annotations

import httpx


class MCPRemoteError(RuntimeError):
    pass


class MCPRemoteToolRunner:
    def __init__(self, mode: str, endpoint: str):
        self.mode = mode
        self.endpoint = endpoint.rstrip("/")

    async def list_tools(self) -> list[dict]:
        if self.mode == "local":
            return [
                {
                    "name": "echo",
                    "description": "Return provided payload",
                    "schema": {"type": "object", "additionalProperties": True},
                }
            ]

        if self.mode == "remote":
            url = f"{self.endpoint}/tools"
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, list):
                    return payload
                raise MCPRemoteError("Remote MCP returned invalid tools payload")
            except (httpx.HTTPError, ValueError) as exc:
                raise MCPRemoteError(f"Failed to fetch tools from MCP endpoint: {exc}") from exc

        raise MCPRemoteError(f"Unsupported MCP mode: {self.mode}")

    async def call_tool(self, tool_name: str, args: dict) -> dict:
        if self.mode == "local":
            if tool_name != "echo":
                raise MCPRemoteError(f"Unknown local tool: {tool_name}")
            return {"tool": tool_name, "result": args}

        if self.mode == "remote":
            url = f"{self.endpoint}/tools/{tool_name}"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json={"args": args})
                    resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, dict):
                    return payload
                raise MCPRemoteError("Remote MCP returned invalid call payload")
            except (httpx.HTTPError, ValueError) as exc:
                raise MCPRemoteError(f"Failed to invoke MCP tool: {exc}") from exc

        raise MCPRemoteError(f"Unsupported MCP mode: {self.mode}")
