"""Compatibility alias for the packaged legacy Gmail backend."""

import sys

from avaya_case_review_runtime import gmail_legacy_backend as _impl

sys.modules[__name__] = _impl
