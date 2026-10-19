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


def test_clean_text_is_unchanged_and_maps_empty():
    scrubbed, mapping = redact.scrub("the deploy runs in us-east-1 on tuesdays")
    assert mapping == {} and "us-east-1" in scrubbed
    assert redact.audit(mapping) == {}
