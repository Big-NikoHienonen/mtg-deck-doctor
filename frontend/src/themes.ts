import { useSyncExternalStore } from "react";

// The app's look, as palettes. Each theme is a plane of the multiverse; its palette becomes the CSS
// custom properties the pages already draw from (--bg, --accent…), set on the root element.

export type Palette = {
  bg: string;
  surface: string;
  border: string;
  text: string;
  textMuted: string;
  // Links, the active tab, the footer bar and primary buttons.
  accent: string;
  // A second color for hover borders and small marks.
  accentGold: string;
  userBubble: string;
  danger: string;
  positive: string;
  // Text on a field of `accent`.
  onAccent: string;
  // The hero's gradient, left to right; the commander's art fades into the right end.
  heroA: string;
  heroB: string;
  heroC: string;
  titleFont: string;
  titleWeight: string;
  titleSpacing: string;
};

export type Theme = {
  id: string;
  name: string;
  blurb: string;
  dark: boolean;
  colors: Palette;
};

const CSS_VARS: Record<keyof Palette, string> = {
  bg: "--bg",
  surface: "--surface",
  border: "--border",
  text: "--text",
  textMuted: "--text-muted",
  accent: "--accent",
  accentGold: "--accent-gold",
  userBubble: "--user-bubble",
  danger: "--danger",
  positive: "--positive",
  onAccent: "--on-accent",
  heroA: "--dv-hero-a",
  heroB: "--dv-hero-b",
  heroC: "--dv-hero-c",
  titleFont: "--dv-title-font",
  titleWeight: "--dv-title-weight",
  titleSpacing: "--dv-title-spacing",
};

const INTER = 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
const serif = (name: string) => `"${name}", Georgia, serif`;
const sans = (name: string) => `"${name}", system-ui, sans-serif`;

export const THEMES: Theme[] = [
  {
    id: "dominaria",
    name: "Dominaria",
    blurb: "Parchment and ink. The classic look, as it is now.",
    dark: false,
    colors: {
      bg: "#efe6d3", surface: "#f7f0de", border: "#c9b98f", text: "#2b2018", textMuted: "#5a4a34",
      accent: "#7a2e2e", accentGold: "#b08c3e", userBubble: "#e3d6b4", danger: "#c0392b", positive: "#3b7d3a", onAccent: "#ffffff",
      heroA: "#2e1214", heroB: "#43181a", heroC: "#5f2626", titleFont: INTER, titleWeight: "700", titleSpacing: "-0.01em",
    },
  },
  {
    id: "innistrad",
    name: "Innistrad",
    blurb: "Gothic horror. Moonlit indigo, bone and blood.",
    dark: true,
    colors: {
      bg: "#12111a", surface: "#1b1926", border: "#3d3753", text: "#ece6d8", textMuted: "#aca5ba",
      accent: "#e0596a", accentGold: "#b7a6dc", userBubble: "#272339", danger: "#ff8c7d", positive: "#7fd0a0", onAccent: "#14070a",
      heroA: "#0a0911", heroB: "#2a1636", heroC: "#5a1f33", titleFont: serif("IM Fell English SC"), titleWeight: "400", titleSpacing: "0.01em",
    },
  },
  {
    id: "kamigawa",
    name: "Kamigawa",
    blurb: "Neon Dynasty. Midnight violet, hot pink and cyan.",
    dark: true,
    colors: {
      bg: "#0c0a18", surface: "#151228", border: "#38335f", text: "#f0ebff", textMuted: "#aca4d4",
      accent: "#ff4fa3", accentGold: "#35e6e0", userBubble: "#1f1b3d", danger: "#ff8f8f", positive: "#4af0b0", onAccent: "#1a0714",
      heroA: "#070514", heroB: "#2b1068", heroC: "#8a1d78", titleFont: sans("Rajdhani"), titleWeight: "700", titleSpacing: "0.02em",
    },
  },
  {
    id: "theros",
    name: "Theros",
    blurb: "Marble and the Aegean. Cool stone, deep blue, laurel gold.",
    dark: false,
    colors: {
      bg: "#eceff4", surface: "#f9fafc", border: "#bac4d6", text: "#18253c", textMuted: "#485a77",
      accent: "#1d4f91", accentGold: "#a87a1f", userBubble: "#dae1ee", danger: "#b0372a", positive: "#2a7a42", onAccent: "#ffffff",
      heroA: "#0b2146", heroB: "#15407c", heroC: "#2d67ad", titleFont: serif("Marcellus"), titleWeight: "400", titleSpacing: "0.01em",
    },
  },
];

// ---- choosing and keeping one ----

const KEY = "mtg-deck-doctor:theme";

// What a browser that hasn't picked a theme gets, and what an id that no longer exists falls back to.
// Keep the :root colors in index.css the same as this theme's, so the page doesn't flash in another
// look before the theme is applied.
export const DEFAULT_THEME = "kamigawa";

export function themeById(id: string): Theme {
  return THEMES.find((t) => t.id === id) ?? THEMES.find((t) => t.id === DEFAULT_THEME) ?? THEMES[0];
}
const listeners = new Set<() => void>();

function stored(): string {
  try {
    const id = localStorage.getItem(KEY);
    if (id && THEMES.some((t) => t.id === id)) return id;
  } catch {
    // no saved choice, or the browser won't say
  }
  return DEFAULT_THEME;
}

let current = stored();

export function applyTheme(id: string): void {
  const theme = themeById(id);
  const root = document.documentElement;
  for (const key of Object.keys(CSS_VARS) as (keyof Palette)[]) root.style.setProperty(CSS_VARS[key], theme.colors[key]);
  root.dataset.theme = theme.id;
  root.style.colorScheme = theme.dark ? "dark" : "light";
}

export function setTheme(id: string): void {
  current = id;
  try {
    localStorage.setItem(KEY, id);
  } catch {
    // the choice still holds for this visit
  }
  applyTheme(id);
  listeners.forEach((listener) => listener());
}

// Puts the saved theme on the page; called once, before anything is drawn.
export function applyStoredTheme(): void {
  applyTheme(current);
}

export function useTheme(): [string, (id: string) => void] {
  const id = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => current,
  );
  return [id, setTheme];
}
