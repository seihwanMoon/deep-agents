"""MCP remote/local integration placeholder for phase 4."""


class MCPRemoteToolRunner:
    def __init__(self, mode: str, endpoint: str):
        self.mode = mode
        self.endpoint = endpoint

    async def list_tools(self) -> list[dict]:
        return [{"name": "placeholder_tool", "mode": self.mode, "endpoint": self.endpoint}]

    async def call_tool(self, tool_name: str, args: dict) -> dict:
        return {"tool": tool_name, "args": args, "mode": self.mode}
