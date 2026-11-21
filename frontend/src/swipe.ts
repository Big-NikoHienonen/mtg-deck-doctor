// The rules for a horizontal swipe, apart from the page: when a touch becomes a swipe rather than a scroll or
// a tap, how far the content follows the finger, and when letting go counts as a swipe. useSwipe.ts applies
// them to an element.

// How far a touch moves (in pixels, either way) before it is judged to be a swipe or a scroll.
export const START = 10;
// A swipe this long goes through on its own.
export const FAR = 80;
// A shorter one goes through if it was quick, which is what a flick is.
export const QUICK = 40;
export const FAST = 0.5; // pixels per millisecond
// A touch is a scroll, not a swipe, when it moves up or down more than this part of how far it moves sideways.
// 0.8 is about 39 degrees from the horizontal: a sideways swipe with a little wobble is still a swipe.
export const STEEP = 0.8;
// Where there is no card to go to, the content gives way a little and no more.
export const RESIST = 0.25;
// The content can be pulled this far across the screen, as a part of its width.
export const MAX_PULL = 0.6;

export type Judgement = "wait" | "swipe" | "scroll";

export function judge(dx: number, dy: number): Judgement {
  if (Math.abs(dx) < START && Math.abs(dy) < START) return "wait";
  return Math.abs(dy) > Math.abs(dx) * STEEP ? "scroll" : "swipe";
}

// Where the content is while the finger is `dx` from where it landed. Left (negative) goes to the next card and
// right to the previous one.
export function pull(dx: number, canNext: boolean, canPrev: boolean, width: number): number {
  const allowed = dx < 0 ? canNext : canPrev;
  const limit = width * MAX_PULL;
  return Math.max(-limit, Math.min(limit, allowed ? dx : dx * RESIST));
}

// Whether letting go `ms` milliseconds after landing, `dx` away, goes to the next or previous card.
export function commits(dx: number, ms: number, canNext: boolean, canPrev: boolean): "next" | "prev" | null {
  const next = dx < 0;
  if (!(next ? canNext : canPrev)) return null;
  const far = Math.abs(dx) >= FAR;
  const flick = Math.abs(dx) >= QUICK && Math.abs(dx) / Math.max(1, ms) >= FAST;
  return far || flick ? (next ? "next" : "prev") : null;
}
