"""Compatibility entry point for the packaged CaseToMD MCP server."""

import sys
from pathlib import Path

try:
    from avaya_case_review_runtime import casetomd_mcp_bridge as _impl
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from avaya_case_review_runtime import casetomd_mcp_bridge as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl
