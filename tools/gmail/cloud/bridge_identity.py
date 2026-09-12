"""Compatibility alias for the packaged bridge identity helpers."""

import sys
from pathlib import Path

try:
    from avaya_case_review_runtime import bridge_identity as _impl
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from avaya_case_review_runtime import bridge_identity as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl
