"""Compatibility alias for the packaged Gmail broker protocol."""

import sys

from avaya_case_review_runtime import gmail_broker_protocol as _impl

sys.modules[__name__] = _impl
