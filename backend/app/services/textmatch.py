"""Loose name matching for spoken searches.

Voice search gives text in Urdu script ("لبرٹی چوک") or a roman spelling that differs from ours ("Kartaba" for
"Qartaba"). Both are reduced to a consonant skeleton (vowels, h, w, y dropped; sound-alike letters merged), so
"لبرٹی چوک", "Liberty Chowk" and "libarti chok" all become "lbrtck".
"""
from __future__ import annotations

import re

_URDU = {
    "ب": "b", "پ": "p", "ت": "t", "ٹ": "t", "ط": "t", "ث": "s", "س": "s", "ص": "s", "ج": "j", "چ": "c",
    "خ": "X", "د": "d", "ڈ": "d", "ذ": "z", "ز": "z", "ض": "z", "ظ": "z", "ژ": "z", "ر": "r", "ڑ": "r",
    "ش": "S", "غ": "g", "ف": "f", "ق": "k", "ک": "k", "ك": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n", "ں": "n",
}
_ROMAN = [("ch", "c"), ("sh", "S"), ("kh", "X"), ("gh", "g"), ("ph", "f"), ("q", "k"), ("ck", "k"),
          ("c", "k"), ("x", "ks"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("jh", "j")]
_ARABIC = re.compile(r"[؀-ۿ]")


def has_urdu(text: str) -> bool:
    return bool(_ARABIC.search(text))


def skeleton(text: str) -> str:
    t = re.sub(r"^\s*\d+[.)]?\s*", "", text.lower())  # stop names start with "10. "
    if has_urdu(t):
        out = "".join(_URDU.get(ch, "") for ch in t)
    else:
        t = re.sub(r"[^a-z]", "", t)
        # "ch" -> "c" first, then lone "c" -> "k"; a placeholder keeps the two apart
        for a, b in _ROMAN:
            t = t.replace(a, b.upper() if b == "c" else b)
        t = t.replace("C", "c")
        out = re.sub(r"[aeiouhwyv]", "", t)
    return re.sub(r"(.)\1+", r"\1", out)  # Urdu writes no double letters: "Qaddafi" -> kdf


def loose_match(q: str, *values: str | None) -> bool:
    """True if the query's skeleton appears in a value's skeleton (3+ consonants), or equals it (short names)."""
    sq = skeleton(q)
    if len(sq) < 2:
        return False
    return any(v and (sq in skeleton(v) if len(sq) >= 3 else sq == skeleton(v)) for v in values)
