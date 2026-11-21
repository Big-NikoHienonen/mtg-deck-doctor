import { useRef, type PointerEvent as ReactPointerEvent } from "react";
import { commits, judge, pull } from "./swipe";

type Options = {
  canPrev: boolean;
  canNext: boolean;
  onPrev: () => void;
  onNext: () => void;
};

type Gesture = { id: number; x: number; y: number; at: number; mode: "pending" | "swipe" | "scroll"; follow: boolean };

// A card's window changes card when it is swiped sideways with a finger: left for the next card, right for the
// previous. Spread `handlers` onto the element and give it `ref`. The element needs `touch-action: pan-y
// pinch-zoom` (cardmodal.css), which leaves up and down scrolling to the browser and sideways to this.
//
// On a phone the element follows the finger and the new card slides in from the side it came from. On a wider
// screen, where the buttons at the sides are fixed to the element and a transform would move them, the card
// just changes. A mouse never swipes, only a finger or a pen, and a touch that starts in a field is left alone
// so text can still be selected.
export function useSwipe({ canPrev, canNext, onPrev, onNext }: Options) {
  const ref = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);

  const settle = (el: HTMLElement) => {
    el.style.transition = "transform 160ms ease-out";
    el.style.transform = "";
    window.setTimeout(() => (el.style.transition = ""), 200);
  };

  // The new card comes in from the side the finger was heading away from.
  const enter = (el: HTMLElement, from: 1 | -1) => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.style.transition = "";
      el.style.transform = "";
      return;
    }
    el.style.transition = "none";
    el.style.transform = `translateX(${from * 48}px)`;
    el.style.opacity = "0";
    void el.offsetWidth; // Make the starting place count before the move to the end.
    el.style.transition = "transform 200ms ease-out, opacity 200ms ease-out";
    el.style.transform = "";
    el.style.opacity = "";
    window.setTimeout(() => (el.style.transition = ""), 240);
  };

  const handlers = {
    onPointerDown(e: ReactPointerEvent<HTMLDivElement>) {
      if (e.pointerType === "mouse" || !e.isPrimary) return;
      if ((e.target as HTMLElement).closest("input, select, textarea, [data-no-swipe]")) return;
      gesture.current = {
        id: e.pointerId,
        x: e.clientX,
        y: e.clientY,
        at: e.timeStamp,
        mode: "pending",
        follow: window.matchMedia("(max-width: 640px)").matches,
      };
    },

    onPointerMove(e: ReactPointerEvent<HTMLDivElement>) {
      const g = gesture.current;
      const el = ref.current;
      if (!g || !el || e.pointerId !== g.id || g.mode === "scroll") return;
      const dx = e.clientX - g.x;
      const dy = e.clientY - g.y;
      if (g.mode === "pending") {
        const judgement = judge(dx, dy);
        if (judgement === "wait") return;
        if (judgement === "scroll") {
          g.mode = "scroll";
          return;
        }
        g.mode = "swipe";
        try {
          // From here on the element gets the finger's moves wherever it goes, and the buttons under it get no click.
          el.setPointerCapture(e.pointerId);
        } catch {
          // The finger was lifted in the meantime; the gesture ends on its own.
        }
      }
      if (g.follow) {
        el.style.transition = "none";
        el.style.transform = `translateX(${pull(dx, canNext, canPrev, el.clientWidth)}px)`;
      }
    },

    onPointerUp(e: ReactPointerEvent<HTMLDivElement>) {
      const g = gesture.current;
      const el = ref.current;
      gesture.current = null;
      if (!g || !el || g.mode !== "swipe" || e.pointerId !== g.id) return;
      const dx = e.clientX - g.x;
      const go = commits(dx, e.timeStamp - g.at, canNext, canPrev);
      if (go === null) {
        if (g.follow) settle(el);
        return;
      }
      (go === "next" ? onNext : onPrev)();
      if (g.follow) enter(el, go === "next" ? 1 : -1);
    },

    onPointerCancel() {
      const g = gesture.current;
      gesture.current = null;
      // The browser took the touch for a scroll, or the touch was interrupted: put the content back.
      if (g?.mode === "swipe" && g.follow && ref.current) settle(ref.current);
    },
  };

  return { ref, handlers };
}
