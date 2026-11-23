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
