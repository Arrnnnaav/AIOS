"""Provider key management.

    py -3.12 -m ghostcursor.providers keys status
    py -3.12 -m ghostcursor.providers keys set <typesafe|nvidia|openrouter>   (prompts; no echo)
    py -3.12 -m ghostcursor.providers keys import-env <path-to-.env> <NAME>=<provider> ...
    py -3.12 -m ghostcursor.providers ping            (live: one tiny request per configured provider)

Keys are stored in Windows Credential Manager under ``Orbyn/<provider>``.
Values are never printed.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from ghostcursor.providers import keys


def _read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ghostcursor.providers")
    commands = parser.add_subparsers(dest="command", required=True)
    key_parser = commands.add_parser("keys")
    key_commands = key_parser.add_subparsers(dest="action", required=True)
    key_commands.add_parser("status")
    setter = key_commands.add_parser("set")
    setter.add_argument("name", choices=keys.KNOWN)
    importer = key_commands.add_parser("import-env")
    importer.add_argument("path", type=Path)
    importer.add_argument(
        "mappings", nargs="+", help="ENV_NAME=provider, e.g. TYPESAFE_API_KEY=typesafe"
    )
    commands.add_parser("ping")
    arguments = parser.parse_args(argv)

    if arguments.command == "keys":
        if arguments.action == "status":
            for name, present in keys.status().items():
                print(f"{name}: {'present' if present else 'missing'}")
            return 0
        if arguments.action == "set":
            value = getpass.getpass(f"{arguments.name} key (not echoed): ")
            keys.set_key(arguments.name, value)
            print(f"{arguments.name}: stored")
            return 0
        env = _read_env(arguments.path)
        for mapping in arguments.mappings:
            env_name, _, provider = mapping.partition("=")
            if provider not in keys.KNOWN:
                print(f"unknown provider {provider!r}")
                return 2
            if not env.get(env_name):
                print(f"{env_name}: not in {arguments.path.name}")
                return 2
            keys.set_key(provider, env[env_name])
            print(f"{provider}: stored from {env_name}")
        return 0

    from ghostcursor.providers import Envelope, Gateway, ProviderError, Tainted

    gateway = Gateway()
    print("available:", gateway.available())
    envelope = Envelope(
        task="connectivity check",
        trusted={"goal": "save the document"},
        tainted={
            "candidates": {
                "c1": Tainted.of("uia_name", "Save"),
                "c2": Tainted.of("uia_name", "Close"),
            }
        },
    )
    try:
        choice = gateway.choose(
            envelope, ("c1", "c2"), question="Which control saves the document?"
        )
        print(
            "jev:",
            choice.choice,
            {k: round(v, 3) for k, v in choice.probabilities.items()},
        )
    except ProviderError as exc:
        print("jev:", exc.kind.value)
    try:
        plan = gateway.plan(envelope)
        print("plan:", [s.expected_change.value for s in plan.steps])
    except ProviderError as exc:
        print("plan:", exc.kind.value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
