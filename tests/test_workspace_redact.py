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


def test_a_private_word_next_to_a_digit_or_underscore_is_hidden():
    """Tier-1 review 14 Nov: file names on screen are the common form."""

    from ghostcursor import redact

    out = redact.scrub("Acme_Proposal_v2.pptx, Acme2026 plan, 7Acme, Acme's", terms=("Acme",))[0]
    assert "Acme" not in out and out.count("[NAME_1]") == 4
    assert redact.scrub("Acmeville and MegaAcme", terms=("Acme",))[0] == "Acmeville and MegaAcme"


def test_private_words_are_found_in_json_text_too():
    """Tier-1 review 14 Nov: a System-Two message is JSON, where a line break
    reads backslash-n and a backslash or quote in a word is doubled."""

    import json

    from ghostcursor import redact

    bs, nl = chr(92), chr(10)
    account = "CORP" + bs + "jsmith"
    message = f"Note for Acme{nl}Health and {account}, also{nl}Zorblat and{nl}acme health"
    sent = json.dumps({"message": message}, ensure_ascii=False)
    out, m = redact.scrub(sent, terms=("Acme Health", "Zorblat", account), json_text=True)
    assert not any(w in out.casefold() for w in ("acme", "health", "zorblat", "jsmith"))
    assert json.loads(out)["message"].count("[NAME_") == 4  # still valid JSON
    assert redact.scrub(message, terms=("Acme Health", account))[0].count("[NAME_") == 3


def test_each_list_of_private_words_keeps_its_own_limit(monkeypatch, tmp_path):
    from ghostcursor import policy, redact, settings

    path = tmp_path / "settings.json"
    settings.set_private_terms(["Secretco"], path)
    org = ";".join(f"org{i}" for i in range(250))
    monkeypatch.setattr(policy, "_value", lambda name: {"PrivateTerms": org}.get(name))
    terms = settings.private_terms(path)
    assert len(terms) == 201 and "Secretco" in terms
    assert redact.scrub("ask Secretco", terms=terms)[0] == "ask [NAME_1]"


def test_a_private_word_of_too_many_words_is_dropped():
    from ghostcursor import redact

    assert redact.clean_terms(["a b c d e f g h", "a b c d e f g h i"]) == ("a b c d e f g h",)


def test_a_private_word_never_breaks_json_text():
    """Tier-1 review 15 Nov: a word starting with n, r or t matched the letter
    of a line-break escape and left invalid JSON."""

    import json

    from ghostcursor import redact

    nl, tab, bs = chr(10), chr(9), chr(92)
    sent = json.dumps({"t": f"Meet me{nl}at the office, says Nat{tab}TIN and{nl}Nat"}, ensure_ascii=False)
    out, m = redact.scrub(sent, terms=("Nat", "TIN"), json_text=True)
    back = json.loads(out)["t"]  # still valid JSON
    assert "Nat" not in back and "TIN" not in back
    assert redact.clean_terms([bs + "share", "share" + bs, "CORP" + bs + "ann"]) == ("CORP" + bs + "ann",)
    # Plain text with a Windows path: the folder name is still hidden.
    assert "Nat" not in redact.scrub("open C:" + bs + "Nat" + bs + "plan.txt", terms=("Nat",))[0]


def test_a_word_that_only_starts_like_a_key_is_not_a_key():
    """Measured 15 Nov 2026: 9 of 239 recorded control names were hidden as
    a key only because "ghostcursor-..." starts with "gho"."""

    from ghostcursor import redact

    for word in ("ghostcursor-investor-deck-content", "skyscraper_floorplan_v2_final", "pkgconfig-dependencies-list", "AKIAvery long word here"):
        assert redact.scrub(word)[0] == word, word
    for key in ("sk-" + "A" * 20, "sk_live_" + "a" * 20, "ghp_" + "a" * 36, "gho_" + "b" * 36,
                "github_pat_" + "c" * 30, "xoxb-" + "1" * 20, "AKIA" + "ABCDEFGHIJKLMNOP", "pk_test_" + "d" * 20):
        assert redact.scrub(f"use {key} now")[0] == "use [KEY_1] now", key


def test_a_private_word_spans_hyphens_underscores_and_json_escapes():
    import json

    from ghostcursor import redact

    for text in ("call-priya-nair", "Priya_Nair.docx", "priya - nair"):
        assert "priya" not in redact.scrub(text, terms=("Priya Nair",))[0].casefold(), text
    sent = json.dumps({"t": "x" + chr(12) + "Fred and" + chr(8) + "fred"}, ensure_ascii=False)
    out = redact.scrub(sent, terms=("Fred",), json_text=True)[0]
    assert "red" not in json.loads(out)["t"].replace("[NAME_1]", "")  # valid JSON, hidden
    # A form feed then "red" reads backslash-f-r-e-d in JSON: "Fred" matches
    # there, and the escape letter must stay or the JSON breaks.
    tricky = json.dumps({"t": "x" + chr(12) + "red " + chr(8) + "ob"}, ensure_ascii=False)
    back = json.loads(redact.scrub(tricky, terms=("Fred", "Bob"), json_text=True)[0])["t"]
    assert back.startswith("x" + chr(12)) and "red" not in back and "ob" not in back


def test_more_provider_key_shapes_are_hidden():
    """Review 15 Nov: Orbyn's own NVIDIA and Tavily keys among them."""

    from ghostcursor import redact

    for key in ("gsk_" + "a" * 40, "nvapi-" + "b" * 40, "tvly-" + "c" * 32, "hf_" + "d" * 34,
                "AIza" + "e" * 35, "ASIA" + "ABCDEFGHIJKLMNOP"):
        assert redact.scrub(f"key={key};")[0] == "key=[KEY_1];", key
    for word in ("hf_short", "tvly-x", "ASIAN culture festival", "AIzawl"):
        assert redact.scrub(word)[0] == word, word


def test_a_windows_path_keeps_no_letter_of_a_private_word():
    from ghostcursor import redact

    bs = chr(92)
    out, m = redact.scrub("C:" + bs + "Users" + bs + "Bob" + bs + "notes", terms=("Bob",))
    assert out == "C:" + bs + "Users" + bs + "[NAME_1]" + bs + "notes" and m == {"[NAME_1]": "Bob"}


def test_a_google_key_ending_in_a_hyphen_is_hidden():
    """Tier-1 review 15 Nov (blocking): about 1 Google key in 64 ends in "-"."""

    import json

    from ghostcursor import redact

    key = "AIza" + "B" * 34 + "-"
    for text in (f"key {key} here", f"key {key}", json.dumps({"t": f"key {key}"})):
        assert key not in redact.scrub(text)[0], text
    assert redact.scrub("AIza" + "B" * 36)[0] == "AIza" + "B" * 36  # too long: not this shape


def test_the_rest_of_the_common_key_shapes_are_hidden():
    from ghostcursor import redact

    secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    for text in ("glpat-" + "a" * 20, "npm_" + "b" * 36, "xai-" + "c" * 40, "pplx-" + "d" * 40,
                 "r8_" + "e" * 37, "aws_secret_access_key = " + secret, '"SecretAccessKey": "' + secret + '"'):
        pass
    assert redact.scrub("aws_secret_access_key = " + secret)[0] == "aws_secret_access_key = [KEY_1]"
    import json as _json
    assert _json.loads(redact.scrub(_json.dumps({"SecretAccessKey": secret}), json_text=True)[0]) == {"SecretAccessKey": "[KEY_1]"}
    for text in ("glpat-" + "a" * 20, "npm_" + "b" * 36, "xai-" + "c" * 40, "pplx-" + "d" * 40,
                 "r8_" + "e" * 37, "aws_secret_access_key = " + secret, '"SecretAccessKey": "' + secret + '"'):
        out = redact.scrub(text)[0]
        assert "[KEY_1]" in out and "aaaa" not in out and secret not in out, text
    assert redact.scrub("the secret is " + secret)[0] == "the secret is " + secret  # unnamed: not guessed


def test_a_lower_case_folder_keeps_no_letter_in_plain_text_but_json_stays_valid():
    import json

    from ghostcursor import redact

    bs = chr(92)
    plain = "C:" + bs + "Users" + bs + "nina" + bs + "deck.pptx"
    out, m = redact.scrub(plain, terms=("Nina",))
    assert out == "C:" + bs + "Users" + bs + "[NAME_1]" + bs + "deck.pptx" and m == {"[NAME_1]": "nina"}
    sent = json.dumps({"t": "a" + chr(10) + "ina and Nina"})
    back = json.loads(redact.scrub(sent, terms=("Nina",), json_text=True)[0])["t"]
    assert back.startswith("a" + chr(10)) and "Nina" not in back and "ina" not in back.replace("[NAME_", "")
