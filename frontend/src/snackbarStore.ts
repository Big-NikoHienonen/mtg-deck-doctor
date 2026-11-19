import { useSyncExternalStore } from "react";

// A short message at the top of the page, for something that went wrong where the page has no place of its
// own to say so: a click on a menu item, a button in a card's window. One at a time; a new message takes
// the place of the one showing. The host (Snackbar.tsx) draws it and takes it down after a few seconds.

export type Snack = { id: number; message: string };

let current: Snack | null = null;
let nextId = 1;
const listeners = new Set<() => void>();

function set(next: Snack | null) {
  current = next;
  listeners.forEach((l) => l());
}

export function showSnackbar(message: string) {
  set({ id: nextId++, message });
}

// Takes down the message with this id, if it is still the one showing (a timer that fires after a newer
// message has replaced it must not take the newer one down).
export function dismissSnackbar(id: number) {
  if (current?.id === id) set(null);
}

export function useSnackbar(): Snack | null {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => current,
  );
}

// "Couldn't remove Sol Ring" and the reason the backend gave, as two sentences.
function sentence(text: string): string {
  const trimmed = text.trim();
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

export function reportFailure(err: unknown, what: string) {
  console.error(what, err);
  const reason = err instanceof Error ? err.message.trim() : "";
  showSnackbar(reason ? `${sentence(what)} ${sentence(reason)}` : sentence(what));
}

// For a handler that has nowhere of its own to show an error. A failure becomes a snackbar saying what was
// attempted (`what` is given the same arguments as the action) and why it failed.
export function orSnackbar<A extends unknown[]>(action: (...args: A) => Promise<unknown>, what: (...args: A) => string) {
  return async (...args: A): Promise<void> => {
    try {
      await action(...args);
    } catch (err) {
      reportFailure(err, what(...args));
    }
  };
}
