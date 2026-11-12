import type { ListSettings } from "./DeckControls";
import { GROUP_LABELS, SORT_LABELS, VIEW_LABELS } from "./deckListModel";

// How a deck's list is shown (view, grouping, sort, extras) is a per-viewer preference, kept in the
// browser and shared by every deck page, the owner's and the one anyone can look at.
const SETTINGS_KEY = "mtg-deck-doctor:deckView";
const DEFAULT_SETTINGS: ListSettings = { view: "text", groupBy: "type", sortBy: "name", showMana: true, showPrices: false };

export function loadSettings(): ListSettings {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "null");
    if (saved && typeof saved === "object") {
      return {
        view: saved.view in VIEW_LABELS ? saved.view : DEFAULT_SETTINGS.view,
        groupBy: saved.groupBy in GROUP_LABELS ? saved.groupBy : DEFAULT_SETTINGS.groupBy,
        sortBy: saved.sortBy in SORT_LABELS ? saved.sortBy : DEFAULT_SETTINGS.sortBy,
        showMana: typeof saved.showMana === "boolean" ? saved.showMana : DEFAULT_SETTINGS.showMana,
        showPrices: typeof saved.showPrices === "boolean" ? saved.showPrices : DEFAULT_SETTINGS.showPrices,
      };
    }
  } catch {
    // no saved settings, or the browser won't say — the defaults do
  }
  return DEFAULT_SETTINGS;
}

export function saveSettings(settings: ListSettings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // per-viewer convenience only — fine if it's unavailable
  }
}
