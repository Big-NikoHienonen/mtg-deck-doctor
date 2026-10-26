// Shared by the swap panel and the placeholder shown while the Doctor's review
// runs, so the placeholder is the same shape as what replaces it.
export const CARD_MAX_WIDTH = 260;

export const TONES = {
  cut: { color: "var(--danger)", glow: "rgba(192, 57, 43, 0.3)", label: "CUT" },
  add: { color: "var(--positive)", glow: "rgba(59, 125, 58, 0.3)", label: "ADD" },
} as const;
