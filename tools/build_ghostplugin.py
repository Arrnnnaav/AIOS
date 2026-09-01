"""Build one deterministic, signed GhostCursor plugin bundle.

The private Ed25519 key is supplied from outside the repository. Only the
public key and resulting bundle are distributable artifacts.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _entry(name: str, raw: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info, raw


def _collect(repo_root: Path, specification: dict) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for item in specification["files"]:
        source = (repo_root / item["source"]).resolve()
        destination = PurePosixPath(item["destination"]).as_posix()
        files[destination] = source.read_bytes()
    for item in specification["trees"]:
        source_root = (repo_root / item["source"]).resolve()
        destination_root = PurePosixPath(item["destination"])
        for source in sorted(source_root.rglob("*")):
            if source.is_file():
                destination = (
                    destination_root / source.relative_to(source_root).as_posix()
                ).as_posix()
                files[destination] = source.read_bytes()
    folded: set[str] = set()
    for name in files:
        if name.casefold() in folded:
            raise ValueError(f"case-colliding plugin output: {name}")
        folded.add(name.casefold())
    return files


def build(spec_path: Path, key_path: Path, output: Path) -> tuple[str, str]:
    repo_root = Path(__file__).resolve().parent.parent
    specification = json.loads(spec_path.read_text(encoding="utf-8"))
    files = _collect(repo_root, specification)
    manifest = {
        "schema_version": 1,
        "plugin_id": specification["plugin_id"],
        "version": specification["version"],
        "plugin_api_version": 2 if specification.get("adapter_api") else 1,
        "core_compatibility": specification["core_compatibility"],
        "applications": specification["applications"],
        "signing_key_id": specification["signing_key_id"],
        "adapter_api": specification.get("adapter_api"),
        "files": {
            name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())
        },
    }
    manifest_bytes = _canonical(manifest)
    private = Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(key_path.read_text(encoding="ascii").strip(), validate=True)
    )
    signature = private.sign(manifest_bytes)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w") as archive:
        for name, raw in (
            ("plugin.json", manifest_bytes),
            ("signature.ed25519", signature),
            *sorted(files.items()),
        ):
            info, value = _entry(name, raw)
            archive.writestr(info, value)
    temporary.replace(output)
    return hashlib.sha256(manifest_bytes).hexdigest(), hashlib.sha256(
        output.read_bytes()
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_digest, bundle_digest = build(args.spec, args.private_key, args.output)
    print(f"manifest_sha256={manifest_digest}")
    print(f"bundle_sha256={bundle_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
