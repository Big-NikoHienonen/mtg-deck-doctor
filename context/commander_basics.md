# Commander format basics

Stable format mechanics only — never card-specific facts (legality, oracle
text, prices) that change over time. Those always come from the live tools
(`lookup_card`, `search_cards`), never from this file.

## Setup

- 100-card singleton deck: exactly one commander plus 99 other cards, no two
  cards with the same name except basic lands.
- Starting life total is 40, not 20.
- Typically multiplayer (usually 3-4 players), free-for-all.
- A player dealt 21+ combat damage by the same commander over the course of
  the game loses, regardless of life total ("commander damage").

## The command zone

- The commander does not start in the player's hand or library — it starts
  in the command zone, a zone outside the normal hand/battlefield/graveyard
  cycle.
- A commander can be cast directly from the command zone any time its
  controller could normally cast it, for its mana cost.
- If a commander would go to the hand, library, graveyard, or exile from
  anywhere, its owner may choose to move it to the command zone instead.
  This is why hand-based "cheat a creature into play" tools (e.g. Sneak
  Attack, Elvish Piper, Quicksilver Amulet, Through the Breach) are
  normally irrelevant for getting a COMMANDER onto the battlefield faster —
  it isn't stuck in hand, it's sitting in the command zone ready to be cast
  for its cost. Those tools matter for other big creatures actually in hand,
  not the commander itself.
- Commander tax: each time a commander is cast from the command zone after
  the first, it costs {2} more than the previous time, cumulative for the
  rest of the game. This resets only if a new game starts.

## Color identity

- A card's color identity is every color of mana symbol in its mana cost
  AND its rules text (including reminder text), plus any color indicator.
  This includes the commander's own card.
- Every other card in the deck must have a color identity that is a subset
  of the commander's color identity. A colorless card is always legal
  regardless of the commander's colors. Basic lands follow this too (a
  Forest has green color identity — it is not automatically legal in a
  deck whose commander isn't green).

## Reading "other" and "another" in oracle text

- When a card's ability says it affects "other" creatures/spells of some
  type, that explicitly EXCLUDES itself. A commander whose ability reduces
  the cost of "other Dragon spells you cast" does NOT reduce its own cost
  — a separate effect without that exclusion (e.g. a generic tribal cost
  reducer) is what's needed to discount the commander itself.

## What this file deliberately leaves out

- The banned list, specific card rulings, and anything else that changes
  over time. Always check current legality via a tool
  (`lookup_card`/`add_card`'s `legal_in_commander` field), never assume
  from this file or from memory.
