def test_dataitem_uses_the_reviewed_microsoft_uia_identifier() -> None:
    from ghostcursor.perception.uia import _CONTROL_TYPE_IDS

    assert _CONTROL_TYPE_IDS["DataItem"] == 50029
