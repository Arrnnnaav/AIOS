"""Pre-egress DLP: scrub sensitive entities out of text before it leaves the
device -- a shared export, or a prompt bound for a cloud/BYOK model -- and keep
a reversible placeholder map *locally* so a model's reply can be rehydrated.

This is Orbyn's answer to the enterprise "LLM gateway" pattern (redact before
transmission, restore on the response): the method is grounded in a teardown of
Microsoft Purview Endpoint DLP (endpointdlp.dll / MipDlp.dll, REA 2026-10-19 --
regex content classification behind Allow/Block blanket policy) and Microsoft
Presidio's recognizer set. D186.

Rule 6: a raw value is NEVER logged or returned in the audit. The map that can
restore values stays with the caller and is never part of what leaves. `audit`
reports category counts only, so telemetry/logs carry no PII.

ponytail: regex recognizers with a Luhn gate on card numbers -- a deliberate,
known ceiling (no ML/NER, no checksum on SSN/IBAN). Covers email, card, SSN,
provider/bearer keys, PEM private-key blocks, JWTs, IBAN, IP, phone. Free-text
passwords ("the password is swordfish") stay out of reach of regex and are the
known residual gap. It favours over-redaction (a false positive only replaces a
non-secret with a placeholder; a false negative leaks). Upgrade path: add
Presidio/GLiNER as a second pass if recall ever matters more than staying local
and dependency-free.
"""

from __future__ import annotations

import re

# (category, pattern). ORDER MATTERS: most specific first so a card is not
# eaten by the loose phone pattern, etc. Each match becomes a stable
# placeholder [CATEGORY_n] (n per distinct original value within one scrub).
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # PEM FIRST so the whole key block goes before EMAIL eats an address inside
    # it. `.*?` is lazy and bounded by the END anchor -> linear, no ReDoS.
    (
        "PEM",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    # Starts only where a run of address characters starts (scrub repeats
    # the pass for addresses that follow one another): a start inside a run
    # without "@" retried to its end, so "a-" * 50k took 24 s (review 25 Nov).
    ("EMAIL", re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    # Each provider's own token shape: the prefix then a separator (or, for
    # AWS, upper-case and digits). A bare "gho"/"sk" start is a word, not a
    # key: "ghostcursor-investor-deck-content" was hidden as a key in 9 of 239
    # recorded control names (docs/evidence/scrub-on-screen-names-2026-11-15.md).
    # Also Groq gsk_, NVIDIA nvapi-, Tavily tvly-, Hugging Face hf_, Google
    # AIza and AWS temporary ASIA keys (review 15 Nov).
    (
        "KEY",
        re.compile(
            r"\b(?:(?:sk|pk|rk)[-_]|gh[pousr]_|github_pat_|xox[baprs]-|gsk_|nvapi-|tvly-|hf_|glpat-|npm_|xai-|pplx-|r8_)[-_A-Za-z0-9]{16,}\b"
            # A Google key may end in "-", after which \b never holds; the
            # fixed length has no shorter match to fall back to (review 15 Nov).
            r"|\bA(?:KI|SI)A[0-9A-Z]{16}\b|\bAIza[-_A-Za-z0-9]{35}(?![-\w])"
        ),
    ),
    # explicit bearer/authorization credential (case-insensitive prefix)
    # An AWS secret access key has no prefix of its own: hidden where it is
    # named (aws_secret_access_key = ..., SecretAccessKey: ...).
    (
        "KEY",
        re.compile(
            r"(?i)(?:(?<=secret_access_key)|(?<=secretaccesskey))(?:[\s\"':=]|\\[\"nrt])+(?P<key>[A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])"
        ),
    ),
    ("KEY", re.compile(r"(?i)\b(?:bearer|authorization:?)\s+[A-Za-z0-9._~+/=-]{8,}")),
    # A value assigned to a name that says it is a secret, however short:
    # DB_PASSWORD=prod_admin_2024, "api_key": "abc123", token: xyz (live run
    # 16 Oct). Only the value goes; the name stays. Every quantifier is
    # bounded (no ReDoS) and a placeholder already there is left alone.
    (
        "KEY",
        re.compile(
            r"(?i)(?<![A-Za-z0-9])[A-Za-z0-9_.-]{0,40}?"
            r"(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)"
            r"[A-Za-z0-9_.-]{0,40}(?:\\?[\"'])?[ \t]{0,3}[:=][ \t]{0,3}(?:\\?[\"'])?"
            r"(?!\[[A-Z]+_\d+\])(?P<key>[^\s\"'\\,;{}\[\]]{4,200})"
        ),
    ),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    # as printed on statements: groups of four, e.g. GB82 WEST 1234 5698 7654 32
    (
        "IBAN",
        re.compile(r"\b[A-Z]{2}\d{2}(?: [A-Z0-9]{4,}){3,7}(?: [A-Z0-9]{1,3})?\b"),
    ),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),  # Luhn-gated below
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("PHONE", re.compile(r"\+?\d[\d ()-]{7,}\d")),
]


#: Credentials and identifiers that have no business at rest in a local store
#: (the Company Brain, knowledge.sqlite, scrubs these on write). Contact details -- email, phone, IP -- are
#: legitimate company facts and stay; they are scrubbed on egress instead.
SECRETS = frozenset({"PEM", "JWT", "KEY", "IBAN", "SSN", "CARD"})


def _luhn_ok(digits: str) -> bool:
    """Luhn checksum -- gates CARD so plain long digit runs (order numbers,
    IDs) are not blanket-redacted as payment cards."""

    ds = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(ds) <= 19:
        return False
    total, parity = 0, len(ds) % 2
    for i, d in enumerate(ds):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_PLACEHOLDER = re.compile(r"\[[A-Z]+_\d+\]")

MAX_TERMS, MAX_TERM_CHARS, MAX_TERM_WORDS = 200, 80, 8


def clean_terms(values, limit: int = MAX_TERMS) -> tuple[str, ...]:
    """Private words as they are kept: text of 2 to 80 characters, spaces
    collapsed, one of each whatever the capitals, at most 200. Anything
    else in ``values`` is dropped, not an error (a hand-edited file)."""

    out: dict[str, str] = {}
    for value in values if isinstance(values, (list, tuple)) else ():
        if not isinstance(value, str):
            continue
        term = " ".join(value.split())
        if (
            2 <= len(term) <= MAX_TERM_CHARS
            and term.count(" ") < MAX_TERM_WORDS  # many gaps: a slow pattern
            and not _PLACEHOLDER.search(term)
            # an edge backslash would match half of an escaped quote in JSON
            and chr(92) not in (term[0], term[-1])
        ):
            out.setdefault(term.casefold(), term)
    return tuple(out.values())[:limit]


def _word(word: str) -> str:
    """A pattern for one word of a private term, as typed or as it reads
    inside JSON text (a backslash or a quote is escaped there)."""

    import json

    plain, quoted = re.escape(word), re.escape(json.dumps(word, ensure_ascii=False)[1:-1])
    return plain if plain == quoted else f"(?:{quoted}|{plain})"


def scrub(
    text: str, categories=None, *, mapping=None, avoid: str = "", terms=(),
    json_text: bool = False,
) -> tuple[str, dict[str, str]]:
    """Return (scrubbed_text, map). Every detected entity is replaced by a
    stable ``[CATEGORY_n]`` placeholder; the map {placeholder: original} lets
    the caller rehydrate a reply later. The same original gets the same
    placeholder within one call. The map NEVER leaves with the text.
    ``categories`` limits the scrub to those categories (e.g. ``SECRETS``).

    ``mapping`` continues an earlier scrub's map, so several texts of one
    request share placeholders (the same original gets the same one, and
    two originals never share one). A placeholder that already occurs in
    ``avoid`` is never issued: it would be confused with text that was
    scrubbed elsewhere and whose original this map does not hold.

    ``terms`` are the person's (or the organisation's) private words --
    names of people, clients, projects -- which no pattern can know.
    Each whole-word occurrence, whatever its capitals, becomes a
    ``[NAME_n]`` placeholder."""

    mapping = {} if mapping is None else mapping
    seen = {original: placeholder for placeholder, original in mapping.items()}
    counts: dict[str, int] = {}
    taken = set(_PLACEHOLDER.findall(avoid))  # one pass, however many there are
    for placeholder in mapping:
        category, _, number = placeholder[1:-1].rpartition("_")
        counts[category] = max(counts.get(category, 0), int(number))

    def _sub(category: str, m) -> str:
        if not isinstance(m, str) and "key" in m.re.groupindex:
            # Only the named part is the secret; the label before it stays.
            return m.group(0)[: m.start("key") - m.start()] + _sub(category, m.group("key"))
        original = m if isinstance(m, str) else m.group(0)
        if category == "CARD" and not _luhn_ok(original):
            return original  # not a real card: leave it
        if original in seen:
            return seen[original]
        counts[category] = counts.get(category, 0) + 1
        while f"[{category}_{counts[category]}]" in taken:
            counts[category] += 1
        placeholder = f"[{category}_{counts[category]}]"
        seen[original] = placeholder
        mapping[placeholder] = original
        return placeholder

    for category, pattern in _PATTERNS:
        if categories is not None and category not in categories:
            continue
        text = pattern.sub(lambda m, c=category: _sub(c, m), text)
        if category == "EMAIL":
            for _ in range(50):  # an address right after the last one replaced
                again = pattern.sub(lambda m, c=category: _sub(c, m), text)
                if again == text:
                    break
                text = again
    terms = clean_terms(list(terms), 2 * MAX_TERMS)  # a person's and an organisation's
    if terms:
        # After the patterns, so a name inside an email address went with
        # the address; longest first, so "Acme Health" wins over "Acme".
        # The edge of a word is a non-letter: Acme_Plan.pptx and Acme2026
        # are hidden, Acmeville is not. The text may be JSON (a System-Two
        # message): a line break between two words reads backslash-n there,
        # and a word may follow one directly (review 14 Nov).
        words = re.compile(
            r"(?:(?<![^\W\d_])|(?<=\\[nrtfb]))(?:"
            + "|".join(
                # between words: spaces, a hyphen or underscore (a saved
                # workflow is named call-priya-nair; review 15 Nov), or a
                # JSON whitespace escape
                r"(?:[\s_-]|\\[nrtfb])+".join(_word(w) for w in t.split())
                for t in sorted(terms, key=len, reverse=True)
            )
            + r")(?![^\W\d_])",
            re.IGNORECASE,
        )
        def _name(m: re.Match[str]) -> str:
            found, at = m.group(0), m.start()
            slashes = 0
            while at - slashes > 0 and m.string[at - slashes - 1] == chr(92):
                slashes += 1
            # Only JSON text has escapes; in a plain Windows path the whole
            # folder name is the word (C:\\Users\\nina; review 15 Nov).
            if json_text and slashes % 2 and found[0] in "nrtfb" and len(found) > 1:
                # In JSON text this first letter is the end of a line-break
                # escape, not of the word: keep it or the JSON breaks, and
                # hide the rest (review 15 Nov).
                return found[0] + _sub("NAME", found[1:])
            return _sub("NAME", found)

        # Never inside a placeholder already in the text.
        pieces = re.split(r"(\[[A-Z]+_\d+\])", text)
        for i in range(0, len(pieces), 2):
            pieces[i] = words.sub(_name, pieces[i])
        text = "".join(pieces)
    return text, mapping


def rehydrate(text: str, mapping: dict[str, str]) -> str:
    """Inverse of ``scrub`` for a model's reply: put originals back where the
    model echoed a placeholder. Unknown placeholders are left untouched."""

    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text


def scrub_tree(value, terms=()):
    """Scrub every string leaf of a JSON-like structure (str / dict / list /
    tuple), returning a scrubbed copy; non-strings pass through. For a one-way
    egress path (no rehydrate), e.g. the System-One/Jev state object -- the
    placeholder map is dropped. Keys are left alone (they are field names, not
    content)."""

    if isinstance(value, str):
        return scrub(value, terms=terms)[0]
    if isinstance(value, dict):
        return {k: scrub_tree(v, terms) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(scrub_tree(v, terms) for v in value)
    if isinstance(value, list):
        return [scrub_tree(v, terms) for v in value]
    return value


def audit(mapping: dict[str, str]) -> dict[str, int]:
    """Category -> count of distinct values redacted. Safe to log/telemeter:
    it carries no raw value, only how many of each kind were held back."""

    out: dict[str, int] = {}
    for placeholder in mapping:
        category = placeholder[1:].rsplit("_", 1)[0]
        out[category] = out.get(category, 0) + 1
    return out


def _demo() -> None:
    sample = (
        "Email ada@acme.io or ada@acme.io again, call +1 (415) 555-0100, "
        "card 4111 1111 1111 1111, ssn 123-45-6789, key sk-ABCDEFGHIJKLMNOP1234, "
        "ip 10.0.0.5, order number 1234567890123 (not a card)."
    )
    scrubbed, m = scrub(sample)
    # nothing sensitive survives in the scrubbed text
    for raw in (
        "ada@acme.io",
        "4111",
        "123-45-6789",
        "sk-ABCDEFGHIJKLMNOP1234",
        "10.0.0.5",
    ):
        assert raw not in scrubbed, raw
    # the same email twice -> one placeholder (dedupe)
    assert scrubbed.count("[EMAIL_1]") == 2 and "[EMAIL_2]" not in scrubbed
    # the real card is redacted under a CARD tag
    assert m.get("[CARD_1]") == "4111 1111 1111 1111"
    # Luhn gate: a real card passes, a random long run is not a valid card
    assert _luhn_ok("4111111111111111") and not _luhn_ok("1234567890123")
    # a non-card long run is only ever over-redacted (e.g. PHONE), never a CARD
    assert not any(
        v.replace(" ", "") == "1234567890123" and p.startswith("[CARD")
        for p, v in m.items()
    )
    # round-trip restores exactly
    assert rehydrate(scrubbed, m) == sample
    # audit carries counts only, never a raw value
    a = audit(m)
    assert a["EMAIL"] == 1 and a["CARD"] == 1 and a["SSN"] == 1
    assert all(isinstance(v, int) for v in a.values())
    assert "ada@acme.io" not in str(a)
    print("ok", a)


if __name__ == "__main__":
    _demo()
