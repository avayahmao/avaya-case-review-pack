"""Compatibility alias for the packaged Gmail broker client."""

import sys

from avaya_case_review_runtime import gmail_broker_client as _impl

sys.modules[__name__] = _impl
