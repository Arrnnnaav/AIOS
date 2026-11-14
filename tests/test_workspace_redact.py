"""Pre-egress DLP redaction (D186). A false negative LEAKS, so these pin that
every entity category is caught, the audit never carries a raw value, and the
round-trip is exact."""

from ghostcursor import redact


def test_scrub_catches_every_category_and_never_leaks_in_the_audit():
    text = (
        "mail ada@acme.io, card 4111 1111 1111 1111, ssn 123-45-6789, "
        "key sk-ABCDEFGHIJKLMNOP1234, ip 10.0.0.5, call +1 (415) 555-0100, "
        "iban GB82WEST12345698765432"
    )
    scrubbed, mapping = redact.scrub(text)
    for raw in (
        "ada@acme.io",
        "4111 1111 1111 1111",
        "123-45-6789",
        "sk-ABCDEFGHIJKLMNOP1234",
        "10.0.0.5",
        "GB82WEST12345698765432",
    ):
        assert raw not in scrubbed  # nothing sensitive survives the scrub
    a = redact.audit(mapping)
    assert {"EMAIL", "CARD", "SSN", "KEY", "IP", "PHONE", "IBAN"} <= set(a)
    # the audit is safe to log: counts only, no raw value anywhere in it
    for raw in ("ada@acme.io", "123-45-6789"):
        assert raw not in str(a)


def test_round_trip_restores_originals_and_dedupes():
    text = "ping ada@acme.io and ada@acme.io"
    scrubbed, mapping = redact.scrub(text)
    assert scrubbed.count("[EMAIL_1]") == 2  # same value -> same placeholder
    assert "[EMAIL_2]" not in scrubbed
    assert redact.rehydrate(scrubbed, mapping) == text


def test_luhn_gate_keeps_plain_long_numbers_off_the_card_tag():
    assert redact._luhn_ok("4111111111111111")
    assert not redact._luhn_ok("1234567890123")
    # the length floor rejects a short run even when it passes the mod-10 sum
    # ("0000" sums to 0, 0 % 10 == 0) -- a 4-digit number is not a card
    assert not redact._luhn_ok("0000")
    # a non-Luhn run is never recorded under a CARD placeholder
    _, mapping = redact.scrub("order 1234567890123")
    assert not any(p.startswith("[CARD") for p in mapping)


def test_hardened_recognizers_catch_pem_jwt_and_bearer():
    """FOLLOWUP #1 before the live-model egress path: PEM private-key blocks,
    JWTs, and bearer/authorization credentials must not leak verbatim."""

    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAK\n-----END RSA PRIVATE KEY-----"
    )
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.dozjgNryP4J3jVmNHl0w5N"
    bearer = "Authorization: Bearer abcDEF123456xyz789"
    for secret, leak in (
        (pem, "MIIBOgIBAAJBAK"),  # key body must not survive
        (jwt, jwt),
        (bearer, "abcDEF123456xyz789"),
    ):
        scrubbed, mapping = redact.scrub(f"here: {secret} end")
        assert leak not in scrubbed, f"{leak!r} leaked"
        assert mapping, f"{secret!r} left unredacted"


def test_scrub_tree_scrubs_nested_string_leaves_only():
    tree = {"a": "mail ada@acme.io", "b": ["card 4111 1111 1111 1111", 5], "n": 3}
    out = redact.scrub_tree(tree)
    assert "ada@acme.io" not in str(out) and "4111 1111 1111 1111" not in str(out)
    assert out["n"] == 3 and 5 in out["b"]  # non-strings pass through unchanged


def test_clean_text_is_unchanged_and_maps_empty():
    scrubbed, mapping = redact.scrub("the deploy runs in us-east-1 on tuesdays")
    assert mapping == {} and "us-east-1" in scrubbed
    assert redact.audit(mapping) == {}


def test_scrub_can_be_limited_to_secrets():
    from ghostcursor import redact

    key = "sk-" + "B" * 20
    text, mapping = redact.scrub(f"mail a@b.example, key {key}", redact.SECRETS)
    assert text == "mail a@b.example, key [KEY_1]" and mapping == {"[KEY_1]": key}
    assert "[EMAIL_1]" in redact.scrub("mail a@b.example")[0]  # unlimited: all


def test_an_iban_written_in_groups_of_four_is_scrubbed():
    from ghostcursor import redact

    for text in (
        "pay GB82 WEST 1234 5698 7654 32 today",
        "DE89 3704 0044 0532 0130 00",
        "GB82 WEST 1234 5698 765432",  # the last groups run together
    ):
        clean = redact.scrub(text, redact.SECRETS)[0]
        assert "[IBAN_1]" in clean and not any(n in clean for n in ("5698", "0532", "7654"))
    for text in ("Meet in room AB12 at noon", "See ID42 PLAN 2026 for details"):
        assert redact.scrub(text, redact.SECRETS)[0] == text  # too short to be one


def test_private_words_are_hidden_whole_word_any_capitals_and_put_back():
    from ghostcursor import redact

    text = "Draft for ACME Health and acme; Acmeville stays. Ask Priya  Nair, ada@acme.io"
    out, m = redact.scrub(text, terms=("Acme", "acme health", "Priya Nair"))
    assert out == "Draft for [NAME_1] and [NAME_2]; Acmeville stays. Ask [NAME_3], [EMAIL_1]"
    assert m["[NAME_1]"] == "ACME Health"  # the longer word wins over "Acme"
    assert redact.rehydrate(out, m) == text
    # No words listed: nothing but the patterns runs.
    assert redact.scrub("Draft for Acme")[0] == "Draft for Acme"
    # A word never rewrites a placeholder that is already in the text.
    assert redact.scrub("see [EMAIL_1] and email", terms=("email", "EMAIL_1"))[0] == (
        "see [EMAIL_1] and [NAME_1]"
    )
    # Characters that mean something to a pattern are taken literally.
    assert redact.scrub("ship C++ (v2) now", terms=("C++ (v2)",))[0] == "ship [NAME_1] now"
    assert redact.scrub_tree({"a": ["Acme"], "b": 3}, ("acme",)) == {"a": ["[NAME_1]"], "b": 3}


def test_private_words_are_cleaned_before_use():
    from ghostcursor import redact

    assert redact.clean_terms(
        ["  Acme   Health ", "ACME HEALTH", "x", "", 7, None, "y" * 81, "[EMAIL_1]", "Orion"]
    ) == ("Acme Health", "Orion")
    assert redact.clean_terms("Acme") == () and redact.clean_terms(None) == ()
    assert len(redact.clean_terms([f"word{i}" for i in range(500)])) == 200


def test_a_private_word_inside_a_longer_word_is_left_alone():
    from ghostcursor import redact

    assert redact.scrub("MegaAcme and Acmeville", terms=("Acme",))[0] == "MegaAcme and Acmeville"
