"""Tests for the profanity check: strong profanity, sexual terms and slurs are caught, in the ways people
disguise them, and card names, puns and ordinary words are not. No network and no model. Run with

    uv run python tests/test_moderation.py
"""

from mtg_deck_doctor.moderation import INNOCENT, ROOTS, WORDS, is_blocked

results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


# What a deck is called, a username, or the two: names that have to get through. The first group is
# card names and words from the game that contain or sit next to a blocked word.
PASSES = [
    "Cockatrice Tribal", "Assassin's Trophy", "Hell's Caretaker", "Damnation", "Grass Wall", "Titania, Protector of Argoth",
    "Tit for Tat", "Document Everything", "Raccoon Rampage", "Sassy Dragons", "Class Warfare", "Analyze the Pollen",
    "Peacock Feather", "Fukushima Dragons", "Janus", "Therapy", "Sakashima's Student", "Spit Flame", "Kill Shot",
    "God-Eternal Kefnet", "Atsushi, the Blazing Sky", "Minamo, School at Water's Edge", "Pass the Torch",
    "The Dragons Shall Kneel Before Me", "Reality Fractured, But Whole", "Jin Sakai, Ghost of Tsushima", "Riddle Me",
    "Cat_Waters", "Atsushi_the_Blazing", "Scunthorpe United", "Dickens of a Deck", "Swank Tribal", "Snigger Cat",
    "Niggling Doubts", "Retardant Foam", "Pussycat Dolls", "Penistone Pete", "Mass Hysteria", "Bass Player", "Shiitake",
    "niko", "Niko_D", "mtg-fan-42", "Dragon Lord 99", "Æther Vial", "Jötun Grunt", "Lim-Dûl's Vault",
]

# What must be refused: plain, in capitals, spaced out, with substitutions and repeated letters, inside a
# longer word, and with letters from other alphabets.
BLOCKED = [
    "fuck", "FUCK you", "f u c k", "f.u.c.k", "f_u_c_k", "f-u-c-k", "fu_ck", "sh1t", "$hit", "sh!t", "fuuuuuck", "fuuuck",
    "motherfucker", "xxfuckxx", "fucking dragons", "n1gg3r", "nigger", "nigga", "c0ck sucker", "cocksucker", "b!tch", "bitch",
    "wanker", "wank", "cunt", "Pussy Power", "pussy", "dickhead", "dick", "retard", "retarded", "fvck", "fcuk", "kill all faggots",
    "faggot", "tr@nny", "whore", "slut", "twat", "bollocks", "asshole", "ass", "arsehole", "anal", "cum", "jizz", "penis",
    "vagina", "dildo", "blowjob", "porn", "pornhub", "hitler", "heil hitler", "nazi", "nazi fan", "kkk", "rapist", "molester",
    "pedophile", "pedo", "incest", "ΡΟRN", "FUСK", "ѕhit", "coon", "spic", "kike", "chink", "gook", "wop", "paki", "tits",
    "boobs", "masturbation", "orgasm", "douchebag", "bullshit", "dumbass", "jackass",
]

wrongly_blocked = [text for text in PASSES if is_blocked(text)]
check("card names, puns and ordinary words get through", not wrongly_blocked, str(wrongly_blocked))
wrongly_passed = [text for text in BLOCKED if not is_blocked(text)]
check("profanity is caught however it is dressed up", not wrongly_passed, str(wrongly_passed))

check("an empty name or one with no letters has nothing in it to refuse", not is_blocked("") and not is_blocked("   ") and not is_blocked("1234 !!!"))
check("capitals and accents don't matter", is_blocked("FuCk") and is_blocked("fúck") and is_blocked("SHÍT"))
check("a run of one-letter words is read as one word, but only a run", is_blocked("s h i t") and not is_blocked("I have a hit"))

# The lists are consistent with each other.
check("every harmless word contains a blocked root, or it has no reason to be in the list", all(any(root in word for root in ROOTS) for word in INNOCENT), str([w for w in INNOCENT if not any(r in w for r in ROOTS)]))
check("no word is in both tiers", not (WORDS & ROOTS), str(sorted(WORDS & ROOTS)))
check("a text can't hide a root in a harmless word and have it counted", not is_blocked("cockatrice cockatrice cockatrice") and is_blocked("cockatrice fuck"))
check("a very long text is checked without trouble", not is_blocked("dragon " * 5000) and is_blocked("dragon " * 5000 + "fuck"))

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
