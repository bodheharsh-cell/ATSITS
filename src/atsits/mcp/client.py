"""Lightweight in-process MCP Client for testing and local integration."""

import json
from typing import Any, Dict, List, Optional
from atsits.mcp.server import MCPServer


class MCPClient:
    """In-process client for communicating with the ATSITS MCP Server."""

    def __init__(self, server: Optional[MCPServer] = None):
        self.server = server or MCPServer()
        self._request_counter: int = 0

    def _next_id(self) -> int:
        self._request_counter += 1
        return self._request_counter

    def initialize(self) -> Dict[str, Any]:
        """Send initialize handshake."""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {},
        }
        resp = self.server.handle_jsonrpc_request(req)
        return resp.get("result", {})

    def ping(self) -> Dict[str, Any]:
        """Send ping."""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "ping",
            "params": {},
        }
        return self.server.handle_jsonrpc_request(req)

    def list_tools(self) -> List[Dict[str, Any]]:
        """Retrieve list of available tools."""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        }
        resp = self.server.handle_jsonrpc_request(req)
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Call an MCP tool with structured arguments.

        Returns:
            Dictionary containing:
            - is_error: bool
            - result / data: parsed JSON payload from tool response
        """
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
        }
        resp = self.server.handle_jsonrpc_request(req)

        if "error" in resp:
            return {
                "is_error": True,
                "error": resp["error"],
            }

        result = resp.get("result", {})
        is_error = result.get("isError", False)
        content_list = result.get("content", [])

        if content_list and content_list[0].get("type") == "text":
            raw_text = content_list[0].get("text", "")
            try:
                parsed_data = json.loads(raw_text)
            except Exception:
                parsed_data = raw_text
            return {
                "is_error": is_error,
                "data": parsed_data,
            }

        return {
            "is_error": is_error,
            "data": result,
        }

    def list_resources(self) -> List[Dict[str, Any]]:
        """Retrieve list of read-only resources."""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "resources/list",
            "params": {},
        }
        resp = self.server.handle_jsonrpc_request(req)
        return resp.get("result", {}).get("resources", [])

    def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a read-only resource by URI."""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "resources/read",
            "params": {"uri": uri},
        }
        resp = self.server.handle_jsonrpc_request(req)
        result = resp.get("result", {})
        contents = result.get("contents", [])
        if contents:
            raw_text = contents[0].get("text", "{}")
            return json.loads(raw_text)
        return {}
