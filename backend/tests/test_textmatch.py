from app.services.textmatch import loose_match, skeleton


def test_urdu_script_matches_roman_stop_names():
    assert loose_match("لبرٹی چوک", "Liberty Chowk")
    assert loose_match("کلمہ چوک", "15. Kalma Chowk")
    assert loose_match("ماڈل ٹاؤن", "16. Model Town")
    assert loose_match("شمع", "11. Shama")


def test_other_roman_spellings_match():
    assert loose_match("Kartaba", "10. Qartaba Chowk")
    assert loose_match("libarti chok", "Liberty Chowk")
    assert skeleton("Kalma Chowk") == skeleton("کلمہ چوک")


def test_unrelated_names_do_not_match():
    assert not loose_match("Model Town", "Liberty Chowk")
    assert not loose_match("a", "Shama")


def test_stop_found_by_alias(client, db):
    """Other official spellings of a stop (aliases) are searched too: typed, and sound-alike."""
    from app.models import BusStop

    db.add(BusStop(code="T-ALIAS", name="Chungi Testpur", lat=31.45, lng=74.35, aliases=["Chungi Amer Testpur"]))
    db.commit()
    names = [s["name"] for s in client.get("/api/stops", params={"q": "Amer Testpur"}).json()]
    assert names == ["Chungi Testpur"]
    hit = client.get("/api/stops", params={"q": "Chungi Amir Testpoor"}).json()  # spoken spelling
    assert [s["name"] for s in hit] == ["Chungi Testpur"] and hit[0]["aliases"] == ["Chungi Amer Testpur"]
