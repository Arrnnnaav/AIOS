"""Read-only verifier for effects produced by the signed PowerPoint adapter."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


PLUGIN_ID = "ghostcursor.powerpoint"
PLUGIN_VERSION = "1.0.0"
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
#: Markup Compatibility.  PowerPoint wraps any transition carrying a newer
#: extension attribute in mc:AlternateContent, so the element is a GRANDCHILD
#: of p:sld, not a child.
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


class Refusal(ValueError):
    pass


def _exact(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise Refusal(f"{label} fields are invalid")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _xml(archive, name):
    try:
        return ET.fromstring(archive.read(name))
    except (KeyError, ET.ParseError) as exc:
        raise Refusal(f"presentation package part is invalid: {name}") from exc


class Package:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if self.path.suffix.casefold() != ".pptx" or not self.path.is_file() or self.path.stat().st_size < 1024:
            raise Refusal("approved PowerPoint output does not exist or is empty")
        try:
            self.archive = zipfile.ZipFile(self.path, "r")
            bad = self.archive.testzip()
        except (OSError, zipfile.BadZipFile) as exc:
            raise Refusal("PowerPoint output is not a readable PPTX package") from exc
        if bad is not None:
            raise Refusal(f"PowerPoint package CRC failed: {bad}")
        self.names = set(self.archive.namelist())
        if "ppt/presentation.xml" not in self.names or "[Content_Types].xml" not in self.names:
            raise Refusal("PowerPoint package lacks required presentation parts")
        self.slides = {}
        for name in sorted(self.names):
            if re.fullmatch(r"ppt/slides/slide[0-9]+\.xml", name):
                root = _xml(self.archive, name)
                c_sld = root.find(f"{{{_P}}}cSld")
                slide_name = c_sld.get("name", "") if c_sld is not None else ""
                self.slides[slide_name] = (name, root)

    def close(self):
        self.archive.close()

    def slide(self, slide_id):
        if slide_id not in self.slides:
            raise Refusal(f"slide {slide_id!r} is absent from saved output")
        return self.slides[slide_id][1]

    def object(self, slide_id, object_id):
        root = self.slide(slide_id)
        for item in root.iter(f"{{{_P}}}cNvPr"):
            if item.get("name") == object_id:
                return item
        raise Refusal(f"object {object_id!r} is absent from slide {slide_id!r}")


def _verify(package, operation_id, p):
    observed = {"bytes": package.path.stat().st_size, "slides": len(package.slides)}
    if operation_id == "powerpoint.create_presentation":
        if package.path != Path(p["output_path"]).resolve(): raise Refusal("created path disagrees")
    elif operation_id == "powerpoint.set_theme":
        theme_sha = hashlib.sha256(_canonical(p).encode()).hexdigest()
        core = _xml(package.archive, "docProps/core.xml")
        if theme_sha not in "".join(core.itertext()):
            tag_parts = [name for name in package.names if name.startswith("ppt/tags/tag") and name.endswith(".xml")]
            if not any(theme_sha in package.archive.read(name).decode("utf-8", "strict") for name in tag_parts):
                raise Refusal("saved presentation does not carry the approved theme digest")
        observed["theme_sha256"] = theme_sha
    elif operation_id == "powerpoint.add_slide":
        package.slide(p["slide_id"]); observed["slide_id"] = p["slide_id"]
    elif operation_id in {"powerpoint.add_text", "powerpoint.add_shape", "powerpoint.add_line", "powerpoint.add_chart"}:
        package.object(p["slide_id"], p["object_id"]); observed["object_id"] = p["object_id"]
        if operation_id == "powerpoint.add_text":
            text = "".join(package.slide(p["slide_id"]).itertext())
            if p["text"] not in text: raise Refusal("saved text does not match the approved text")
    elif operation_id == "powerpoint.add_notes":
        expected = p["text"]
        note_parts = [name for name in package.names if re.fullmatch(r"ppt/notesSlides/notesSlide[0-9]+\.xml", name)]
        if not any(expected in "".join(_xml(package.archive, name).itertext()) for name in note_parts):
            raise Refusal("approved speaker notes are absent")
    elif operation_id == "powerpoint.add_animation":
        marker = package.object(p["slide_id"], p["object_id"])
        root = package.slide(p["slide_id"])
        timing = root.find(f"{{{_P}}}timing")
        if timing is None: raise Refusal("saved slide has no animation timeline")
        shape_id = marker.get("id")
        if not any(item.get("spid") == shape_id for item in timing.iter()):
            raise Refusal("animation timeline does not target the approved object")
    elif operation_id == "powerpoint.set_transition":
        root = package.slide(p["slide_id"])
        found = _slide_transitions(root)
        observed["transition_elements"] = len(found)
        if not found and p["effect"] != "none":
            raise Refusal("saved slide has no approved transition")
    elif operation_id == "powerpoint.save_presentation":
        if package.path != Path(p["output_path"]).resolve(): raise Refusal("saved path disagrees")
    elif operation_id == "powerpoint.inspect_presentation":
        if not package.slides: raise Refusal("final presentation contains no slides")
        observed["slide_ids"] = sorted(package.slides)
    else:
        raise Refusal("verifier does not own this operation")
    return observed



def _slide_transitions(root):
    """Every p:transition declared at slide level, including wrapped ones.

    A transition that carries a newer extension attribute -- p14:dur, which
    PowerPoint writes for any transition with a duration -- is emitted inside
    mc:AlternateContent, with an mc:Choice holding the extended form and an
    mc:Fallback holding the plain one. The element is then a grandchild of
    p:sld and `root.find()` cannot see it, because find() matches direct
    children only. That is measured, not assumed: every transition this plan
    sets has a duration, so every one of them lands there.

    Scoped deliberately to slide level and one AlternateContent below it,
    rather than a whole-subtree search. A transition is only meaningful in
    those positions, and this project has already paid for matching that was
    looser than the thing it was trying to identify.
    """

    found = []
    for child in root:
        if child.tag == f"{{{_P}}}transition":
            found.append(child)
        elif child.tag == f"{{{_MC}}}AlternateContent":
            for branch in child:
                found.extend(
                    item for item in branch if item.tag == f"{{{_P}}}transition"
                )
    return found


def main():
    if sys.argv[1:] != ["--json"]: return 2
    request = json.loads(sys.stdin.readline())
    _exact(request, {"node", "output_path", "plugin_id", "plugin_version", "session_nonce", "target", "type", "validation_sha256", "verifier_sha256"}, "verification request")
    _exact(request["node"], {"node_id", "operation_id", "parameters"}, "verification node")
    own_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if request["type"] != "verify" or request["plugin_id"] != PLUGIN_ID or request["plugin_version"] != PLUGIN_VERSION or request["verifier_sha256"] != own_sha or _SHA_RE.fullmatch(request["validation_sha256"]) is None:
        raise Refusal("verifier authority disagrees")
    package = None
    try:
        package = Package(request["output_path"])
        observed = _verify(package, request["node"]["operation_id"], request["node"]["parameters"])
        outcome, detail = "verified", "saved PPTX independently verifies the approved effect"
    except Exception as exc:
        observed, outcome, detail = {}, "refused", f"{type(exc).__name__}: {exc}"
    finally:
        if package is not None: package.close()
    sys.stdout.write(_canonical({"detail": detail, "node_id": request["node"]["node_id"], "observed": observed, "outcome": outcome, "session_nonce": request["session_nonce"], "type": "verification_result", "validation_sha256": request["validation_sha256"]}) + "\n")
    return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n"); raise SystemExit(3)
