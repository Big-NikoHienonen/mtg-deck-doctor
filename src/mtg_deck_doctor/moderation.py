"""A check for profanity in the text people choose to show others: usernames and deck names.

The list is short and strict about strong profanity, sexual terms and slurs, and leaves mild words
(damn, hell, crap) alone on purpose. Deck names are often card names and puns, so a filter that flags
"Hell's Caretaker", "Cockatrice" or "Assassin's Trophy" is worse than none. Two tiers keep it that way:

- ROOTS are strong enough to flag inside a longer word ("fucking", "motherfucker", "xxfuckxx"), except in
  the INNOCENT words that happen to contain one.
- WORDS are short or ambiguous ("cum", "tit", "coon"), so they only count as a whole word. "Document",
  "titan" and "raccoon" pass.

Before the words are compared, the text is normalised: accents, look-alike letters and common
substitutions are undone ("sh1t", "$hit", "fuuuck"), and letters spelled out one or two at a time are
joined ("f.u.c.k", "fu_ck"). Separators are never removed wholesale, because that makes words out of
neighbours: "Cat_Waters" would read "twat". `tests/test_moderation.py` holds card names that must pass
and tricks that must not.
"""

import re
import unicodedata

# Flagged anywhere inside a word. Every one of these is something no ordinary word contains, apart from
# the INNOCENT words below.
ROOTS = frozenset(
    """
    fuck fcuk phuck fvck
    shit
    cunt bitch whore slut twat wank bollock
    dick cock pussy
    nigg faggot fagot tranny retard
    rapist molest pedophile paedophile incest
    penis vagina dildo blowjob handjob cumshot jizz orgasm masturbat fellatio cunnilingus
    asshole arsehole douche dumbass jackass asswipe asshat assclown
    hitler nazi
    porn kkk
    """.split()
)

# Flagged only as a whole word, because each is inside harmless words too.
WORDS = frozenset(
    """
    ass arse anal anus cum tits boob boobs hoe
    fag fags dyke dykes coon coons spic spick kike chink gook wop paki
    fck fuk fux
    rape raped raping pedo
    nig nigga niggas
    jap japs
    """.split()
)

# Harmless words that contain a ROOT, which are taken out before a ROOT is looked for. Anything in
# Magic's card names and rules text that contains one is here, and a few everyday words and places.
INNOCENT = frozenset(
    """
    cockatrice cockatrices cockatoo cocktail cockpit cockroach cockney cockburn peacock peacocks
    cocker cockerel cockle cocky cockade hancock hitchcock woodcock shuttlecock stopcock babcock
    alcock wilcock willcock
    dickens dickinson dickson dickerson dickey dickie dickman benedick
    swank swanky
    nazir nazim nazia
    slutsky
    snigger sniggering niggle niggling niggardly
    retardant retardants
    scunthorpe penistone
    pussycat pussywillow
    """.split()
)

# Substitutions people use to get past a filter, and letters from other alphabets that look like ours.
_SUBSTITUTIONS = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g", "@": "a", "$": "s", "!": "i", "|": "i", "+": "t", "€": "e", "£": "l"}
)
_LOOKALIKES = str.maketrans(
    {
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ѕ": "s", "ј": "j", "ɡ": "g", "ɑ": "a",
        "α": "a", "ε": "e", "ο": "o", "ι": "i", "κ": "k", "ν": "v", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
        "ı": "i", "ø": "o", "ł": "l", "đ": "d",
    }
)


def _plain(text: str) -> str:
    """Lower case, accents taken off, look-alike letters turned into ours."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).translate(_LOOKALIKES)


def _tokens(text: str) -> list[str]:
    """The words of `text`, and, for each run of one- and two-letter fragments ("f u c k", "fu ck"), the run
    joined into one more word."""
    words = re.findall(r"[a-z]+", text)
    out = list(words)
    run: list[str] = []
    for word in [*words, ""]:
        if word and len(word) <= 2:
            run.append(word)
            continue
        if len(run) > 1:
            out.append("".join(run))
        run = []
    return out


def _repeat_variants(word: str) -> set[str]:
    """The word as typed, and with any run of three or more of a letter cut to one or to two."""
    return {word, re.sub(r"(.)\1{2,}", r"\1", word), re.sub(r"(.)\1{2,}", r"\1\1", word)}


def _has_root(word: str) -> bool:
    for superword in INNOCENT:
        word = word.replace(superword, " ")
    return any(root in variant for variant in _repeat_variants(word) for root in ROOTS)


def is_blocked(text: str) -> bool:
    """Whether `text` has profanity in it."""
    plain = _plain(text)
    for candidate in (plain, plain.translate(_SUBSTITUTIONS)):
        for token in _tokens(re.sub(r"[^a-z]+", " ", candidate)):
            if any(variant in WORDS for variant in _repeat_variants(token)) or _has_root(token):
                return True
    return False
