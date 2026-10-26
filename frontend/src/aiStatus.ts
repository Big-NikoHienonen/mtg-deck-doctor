import { useSyncExternalStore } from "react";

// Whether the Doctor — the model behind the chat, the reviews and the
// suggestions — can be reached. One answer for the whole page: the first model
// call that fails for a reason outside the request (no credits, a rejected key,
// rate limiting, an outage) records it here, and everything that would call the
// model again waits.

export type AiProblem = {
  code: string;
  message: string;
  // When waiting alone is expected to fix it (ms since epoch), or null when
  // someone has to do something first and then check.
  until: number | null;
};

let problem: AiProblem | null = null;
const listeners = new Set<() => void>();

function set(next: AiProblem | null) {
  problem = next;
  listeners.forEach((l) => l());
}

export function reportAiProblem(body: { detail?: string; code: string; retry_after?: number | null }) {
  set({
    code: body.code,
    message: body.detail ?? "The Doctor isn't available right now.",
    until: body.retry_after ? Date.now() + body.retry_after * 1000 : null,
  });
}

export function clearAiProblem() {
  if (problem) set(null);
}

// True while the Doctor is known to be unavailable and the wait isn't over.
// For code that would start a model call on its own.
export function aiBlocked(): boolean {
  return problem !== null && (problem.until === null || Date.now() < problem.until);
}

export function useAiProblem(): AiProblem | null {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => problem,
  );
}
