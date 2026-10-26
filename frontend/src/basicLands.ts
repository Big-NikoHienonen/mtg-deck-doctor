// Basic lands are exempt from the singleton rule (deck.py) — used wherever
// the frontend needs to mirror that one exemption for its own convenience
// checks (it's never the actual gate; add_card's server-side validation is).
export const BASIC_LAND_NAMES = new Set(["Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"]);
