"""Local MCP Server implementing JSON-RPC 2.0 protocol over stdio and in-memory transports."""

from datetime import datetime
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
from atsits.mcp.audit import MCPAuditLogger
from atsits.mcp.permissions import PermissionLevel, PermissionPolicy
from atsits.mcp.resources import MCPResourceManager
from atsits.mcp.schemas import (
    ErrorCode,
    ToolCategory,
    ToolErrorResponse,
    ToolSuccessResponse,
)
from atsits.mcp.tools import MCPToolRegistry

logger = logging.getLogger(__name__)

MCP_SERVER_NAME: str = "atsits-mcp-server"
MCP_PROTOCOL_VERSION: str = "2024-11-05"


class MCPServer:
    """Local-first Model Context Protocol (MCP) Server for ATSITS."""

    def __init__(
        self,
        tool_registry: Optional[MCPToolRegistry] = None,
        resource_manager: Optional[MCPResourceManager] = None,
        permission_policy: Optional[PermissionPolicy] = None,
        audit_logger: Optional[MCPAuditLogger] = None,
    ):
        self.tools = tool_registry or MCPToolRegistry()
        self.resources = resource_manager or MCPResourceManager(tool_registry=self.tools)
        self.permissions = permission_policy or PermissionPolicy(PermissionLevel.RESEARCH)
        self.audit = audit_logger or MCPAuditLogger()

    def handle_jsonrpc_request(self, req: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a raw JSON-RPC 2.0 request dict and return response dict."""
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if not method:
            return self._make_rpc_error(req_id, -32600, "Invalid Request: missing method")

        try:
            if method == "initialize":
                return self._handle_initialize(req_id, params)
            elif method == "ping":
                return self._make_rpc_success(req_id, {})
            elif method == "tools/list":
                return self._handle_tools_list(req_id)
            elif method == "tools/call":
                return self._handle_tools_call(req_id, params)
            elif method == "resources/list":
                return self._handle_resources_list(req_id)
            elif method == "resources/read":
                return self._handle_resources_read(req_id, params)
            else:
                return self._make_rpc_error(req_id, -32601, f"Method not found: '{method}'")
        except Exception as err:
            logger.exception(f"Unhandled error in RPC method '{method}': {err}")
            return self._make_rpc_error(req_id, -32603, f"Internal service error: {err}")

    def _handle_initialize(self, req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        return self._make_rpc_success(
            req_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "serverInfo": {
                    "name": MCP_SERVER_NAME,
                    "version": "1.0.0",
                },
                "capabilities": {
                    "tools": {},
                    "resources": {},
                },
            },
        )

    def _handle_tools_list(self, req_id: Any) -> Dict[str, Any]:
        tool_defs = self.tools.list_tool_definitions()
        tools_payload = [
            {
                "name": t.name,
                "description": f"[{t.category.value}] {t.description}",
                "inputSchema": t.input_schema,
            }
            for t in tool_defs
        ]
        return self._make_rpc_success(req_id, {"tools": tools_payload})

    def _handle_tools_call(self, req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        call_id = str(req_id) if req_id is not None else f"req_{int(time.time() * 1000)}"

        if not tool_name:
            return self._make_rpc_error(req_id, -32602, "Missing tool name in tools/call")

        category = self.tools.get_tool_category(tool_name)
        start_time = time.perf_counter()

        try:
            # 1. Permission check
            self.permissions.validate_tool_access(tool_name, category)

            # 2. Tool execution
            result_data = self.tools.execute_tool(tool_name, arguments)
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            # 3. Log audit success
            self.audit.log_invocation(
                request_id=call_id,
                tool_name=tool_name,
                category=category.value,
                arguments=arguments,
                duration_ms=duration_ms,
                status="SUCCESS",
            )

            # Format standard MCP tool call response
            content_text = json.dumps(result_data, default=str)
            return self._make_rpc_success(
                req_id,
                {
                    "content": [{"type": "text", "text": content_text}],
                    "isError": False,
                },
            )

        except PermissionError as perm_err:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            self.audit.log_invocation(
                request_id=call_id,
                tool_name=tool_name,
                category=category.value,
                arguments=arguments,
                duration_ms=duration_ms,
                status="ERROR",
                error_code=ErrorCode.PERMISSION_DENIED.value,
                error_message=str(perm_err),
            )
            err_payload = ToolErrorResponse(
                error_code=ErrorCode.PERMISSION_DENIED,
                message=str(perm_err),
            )
            return self._make_rpc_success(
                req_id,
                {
                    "content": [{"type": "text", "text": err_payload.model_dump_json()}],
                    "isError": True,
                },
            )

        except KeyError as key_err:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            self.audit.log_invocation(
                request_id=call_id,
                tool_name=tool_name,
                category=category.value,
                arguments=arguments,
                duration_ms=duration_ms,
                status="ERROR",
                error_code=ErrorCode.TRADE_NOT_FOUND.value,
                error_message=str(key_err),
            )
            err_payload = ToolErrorResponse(
                error_code=ErrorCode.TRADE_NOT_FOUND,
                message=str(key_err),
            )
            return self._make_rpc_success(
                req_id,
                {
                    "content": [{"type": "text", "text": err_payload.model_dump_json()}],
                    "isError": True,
                },
            )

        except ValueError as val_err:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            self.audit.log_invocation(
                request_id=call_id,
                tool_name=tool_name,
                category=category.value,
                arguments=arguments,
                duration_ms=duration_ms,
                status="ERROR",
                error_code=ErrorCode.INVALID_PARAMETER.value,
                error_message=str(val_err),
            )
            err_payload = ToolErrorResponse(
                error_code=ErrorCode.INVALID_PARAMETER,
                message=str(val_err),
            )
            return self._make_rpc_success(
                req_id,
                {
                    "content": [{"type": "text", "text": err_payload.model_dump_json()}],
                    "isError": True,
                },
            )

        except Exception as gen_err:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            self.audit.log_invocation(
                request_id=call_id,
                tool_name=tool_name,
                category=category.value,
                arguments=arguments,
                duration_ms=duration_ms,
                status="ERROR",
                error_code=ErrorCode.SERVICE_ERROR.value,
                error_message=str(gen_err),
            )
            err_payload = ToolErrorResponse(
                error_code=ErrorCode.SERVICE_ERROR,
                message=str(gen_err),
            )
            return self._make_rpc_success(
                req_id,
                {
                    "content": [{"type": "text", "text": err_payload.model_dump_json()}],
                    "isError": True,
                },
            )

    def _handle_resources_list(self, req_id: Any) -> Dict[str, Any]:
        res_list = self.resources.list_resources()
        return self._make_rpc_success(req_id, {"resources": res_list})

    def _handle_resources_read(self, req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        uri = params.get("uri")
        if not uri:
            return self._make_rpc_error(req_id, -32602, "Missing uri in resources/read")

        try:
            content = self.resources.read_resource(uri)
            return self._make_rpc_success(
                req_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": json.dumps(content, default=str),
                        }
                    ]
                },
            )
        except KeyError as err:
            return self._make_rpc_error(req_id, -32602, f"Resource not found: {err}")

    def _make_rpc_success(self, req_id: Any, result: Any) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }

    def _make_rpc_error(self, req_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": code,
                "message": message,
            },
        }

    def run_stdio(self) -> None:
        """Run standard I/O (stdio) JSON-RPC line loop."""
        logger.info(f"Starting ATSITS MCP stdio server ({MCP_SERVER_NAME} v1.0.0)...")
        for line in sys.stdin:
            clean_line = line.strip()
            if not clean_line:
                continue
            try:
                req = json.loads(clean_line)
                resp = self.handle_jsonrpc_request(req)
                resp_str = json.dumps(resp)
                sys.stdout.write(resp_str + "\n")
                sys.stdout.flush()
            except Exception as err:
                err_resp = self._make_rpc_error(None, -32700, f"Parse error: {err}")
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
