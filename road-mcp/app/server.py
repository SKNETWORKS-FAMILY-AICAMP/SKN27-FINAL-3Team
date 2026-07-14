import asyncio
import logging
from typing import Any

from app.config import get_settings
from app.road_tool import inspect_road_environment

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore[assignment]


settings = get_settings()
logging.basicConfig(level=settings.road_log_level)


if FastMCP is not None:
    mcp = FastMCP("road-environment-mcp")

    @mcp.tool()
    async def inspect_road_environment_tool(payload: dict[str, Any]) -> dict[str, Any]:
        """Inspect road environment near an accident location."""
        return await inspect_road_environment(payload)
else:
    mcp = None


def main() -> None:
    if mcp is None:
        raise RuntimeError("mcp package is not installed. Run `pip install -r requirements.txt`.")

    transport = settings.road_mcp_transport
    if transport in {"streamable-http", "http"}:
        # The MCP SDK owns the concrete HTTP transport details. Keep this setting
        # explicit so Docker/Supervisor wiring can settle on the final endpoint.
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
