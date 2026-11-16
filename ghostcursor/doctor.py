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
            "cloud models (your accounts)",
            bool(ready),
            "ready: " + ", ".join(sorted(ready))
            if ready
            else "sign in with ChatGPT or paste a key under Accounts",
        )
    except Exception as exc:  # pragma: no cover - defensive
        return Check("cloud models (your accounts)", False, f"could not check ({exc})")


def _local_model() -> Check:
    """Is a model running on this computer (Ollama), so Orbyn can answer and
    point with nothing sent anywhere? A loopback check only."""

    import socket

    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.3):
            up = True
    except OSError:
        up = False
    return Check(
        "model on this computer (Ollama)",
        up,
        "ready" if up else "install Ollama (ollama.com), then run: ollama pull qwen3:4b-instruct",
    )


def _rea() -> Check:
    """REA stays connected for competitor research: config present + npx on PATH."""

    import json
    import shutil
    from pathlib import Path

    try:
        # Resolve against the repo root, not the cwd: readiness must not flip
        # with the directory doctor is run from.
        mcp = Path(__file__).resolve().parents[1] / ".mcp.json"
        cfg = json.loads(mcp.read_text(encoding="utf-8"))
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

    import sys

    if not ok and getattr(sys, "frozen", False):  # no pip in the packaged app
        install = "not included in this build of Orbyn"
    return Check(name, ok, "ready" if ok else install)


def checks() -> list[Check]:
    """Every capability's readiness, best-effort. Always returns; never raises."""

    import sys

    out = [_models(), _local_model()]
    frozen = bool(getattr(sys, "frozen", False))  # the packaged app: no Python console
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
                else (
                    "optional; Orbyn listens with Whisper until it is installed"
                    if frozen
                    else "py -3.12 -m ghostcursor.listen_kws to install the KWS model "
                    "(Orbyn uses Whisper for the wake word until then)"
                ),
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
    if not frozen:  # a developer tool; meaningless in the packaged app
        out.append(_rea())
    return out


def report() -> str:
    found = checks()
    lines = ["Orbyn readiness -- what is on, and how to turn on the rest:"]
    for c in found:
        lines.append(f"  [{'ok ' if c.ready else 'off'}] {c.name}: {c.hint}")
    if all(c.ready for c in found):
        lines.append("\N{ROCKET} all systems go -- every capability is on.")
    return "\n".join(lines)


def main(argv=None) -> int:
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if "--json" in argv:
        import json
        from dataclasses import asdict

        print(json.dumps([asdict(c) for c in checks()], indent=2))
        return 0
    print(report())
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
