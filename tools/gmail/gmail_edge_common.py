"""Compatibility alias for the packaged Gmail Edge helpers."""

import sys

from avaya_case_review_runtime import gmail_edge_common as _impl

sys.modules[__name__] = _impl
