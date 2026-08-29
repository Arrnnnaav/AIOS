"""Installable, data-only GhostCursor application plugins."""

from ghostcursor.plugins.bundle import BundleVerificationError, VerifiedBundle, verify_bundle
from ghostcursor.plugins.compatibility import CompatibilityResult, check_core_compatibility

__all__ = [
    "BundleVerificationError",
    "CompatibilityResult",
    "VerifiedBundle",
    "check_core_compatibility",
    "verify_bundle",
]
