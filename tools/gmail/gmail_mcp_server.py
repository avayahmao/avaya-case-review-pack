"""Compatibility entry point for the packaged Gmail MCP server."""

import asyncio
import sys
from pathlib import Path

try:
    from avaya_case_review_runtime import gmail_mcp_server as _impl
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from avaya_case_review_runtime import gmail_mcp_server as _impl

if __name__ == "__main__":
    raise SystemExit(asyncio.run(_impl.main()))

sys.modules[__name__] = _impl
