"""Orbyn (code name GhostCursor): a Windows desktop guide and narrow, signed
automation harness. The package, payload paths and signed digests keep the
``ghostcursor`` name (CLAUDE.md); ``Orbyn`` is the product name."""

#: Single source of truth for the product version. Support, telemetry, the
#: update check and the signed-bundle core-compatibility range all read this,
#: so bump it here and nowhere else. 0.x = pre-1.0; the owner sets the public
#: marketing version at the first paid release.
__version__ = "0.2.0"
