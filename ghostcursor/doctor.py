"""One self-check of what is ready and what to turn on (agent-reach's `doctor`
idea, github.com/Panniantong/agent-reach): Orbyn's capabilities degrade
gracefully -- voice falls back to Whisper, the fast wake word to Whisper, the
BYOK gateway from one account to the next -- so the honest thing is to report
each capability's state and the one thing to do to enable a missing one.

No network and no secret values: presence only (which keys exist, never their
contents), matching the privacy rule. Every probe is wrapped so one broken
check never hides the rest. Run it with ``py -3.12 -m ghostcursor.doctor`` or
``/doctor`` in the workspace console.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    name: str
    ready: bool
    hint: str  # how it is provided if ready, else the one thing to do


def _has(module: str) -> bool:
    """Is an optional dependency importable, without importing it?"""

    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def _models() -> Check:
    try:
        from ghostcursor.providers import keys

        ready = [name for name, present in keys.status().items() if present]
        return Check(
            "models (BYOK)",
            bool(ready),
            "ready: " + ", ".join(sorted(ready))
            if ready
            else "sign in with ChatGPT (/providers signin) or set a key in the app",
        )
    except Exception as exc:  # pragma: no cover - defensive
        return Check("models (BYOK)", False, f"could not check ({exc})")


def _rea() -> Check:
    """REA stays connected for competitor research: config present + npx on PATH."""

    import json
    import shutil
    from pathlib import Path

    try:
        cfg = json.loads(Path(".mcp.json").read_text(encoding="utf-8"))
        configured = "rea" in cfg.get("mcpServers", cfg.get("servers", cfg))
    except Exception:
        configured = False
    npx = shutil.which("npx") is not None
    return Check(
        "REA (reverse-engineering MCP)",
        configured and npx,
        "ready (npx fetches it on first use)"
        if configured and npx
        else ("install Node.js (npx) " if not npx else "")
        + ("" if configured else "add the rea server to .mcp.json"),
    )


def _dep(name: str, ok: bool, install: str) -> Check:
    """A capability gated on an optional dependency: 'ready' when present, else
    the one command to enable it."""

    return Check(name, ok, "ready" if ok else install)


def checks() -> list[Check]:
    """Every capability's readiness, best-effort. Always returns; never raises."""

    out = [_models()]
    out.append(
        _dep(
            "voice (Whisper)",
            _has("faster_whisper") and _has("sounddevice"),
            "pip install faster-whisper sounddevice",
        )
    )
    try:
        import ghostcursor.listen_kws as kws

        ok = kws.available()
        out.append(
            Check(
                "fast wake word (Hey Bro)",
                ok,
                "ready"
                if ok
                else "py -3.12 -m ghostcursor.listen_kws to install the KWS model "
                "(Orbyn uses Whisper for the wake word until then)",
            )
        )
    except Exception as exc:  # pragma: no cover - defensive
        out.append(Check("fast wake word (Hey Bro)", False, f"could not check ({exc})"))
    out.append(
        _dep(
            "browser control",
            _has("websocket"),
            "pip install websocket-client, and install Chrome or Edge",
        )
    )
    out.append(
        _dep(
            "Act / Teach (input + windows)",
            _has("win32api") and _has("win32gui"),
            "pip install pywin32 (Windows only)",
        )
    )
    out.append(_rea())
    return out


def report() -> str:
    lines = ["Orbyn readiness -- what is on, and how to turn on the rest:"]
    for c in checks():
        lines.append(f"  [{'ok ' if c.ready else 'off'}] {c.name}: {c.hint}")
    return "\n".join(lines)


def main(argv=None) -> int:
    print(report())
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
