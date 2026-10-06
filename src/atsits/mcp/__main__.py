"""CLI entrypoint to run ATSITS MCP Server locally over stdio."""

import logging
from atsits.mcp.server import MCPServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> None:
    server = MCPServer()
    server.run_stdio()


if __name__ == "__main__":
    main()
