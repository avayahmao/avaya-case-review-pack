"""Compatibility alias for the packaged Gmail broker state helpers."""

import sys

from avaya_case_review_runtime import gmail_broker_state as _impl

sys.modules[__name__] = _impl
