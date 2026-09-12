"""Compatibility entry point for the packaged Gmail Edge broker."""

import sys
from pathlib import Path

try:
    from avaya_case_review_runtime import gmail_edge_broker as _impl
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from avaya_case_review_runtime import gmail_edge_broker as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl
