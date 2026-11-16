import { useSyncExternalStore } from "react";
import { getAuthStatus, logIn, logOut, onUnauthorized } from "./api";

// Whether this browser is signed in. One answer for the whole page: the gate (AuthGate.tsx) asks the
// backend once, and the app bar reads the same state to show or hide Sign out. When the backend
// isn't asking for a password at all (local development), `required` is false and nothing here shows.

export type AuthState = {
  // False until the backend has been asked, and again while it is asked a second time.
  checked: boolean;
  // The backend couldn't be reached.
  unreachable: boolean;
  required: boolean;
  // False when the backend has no account yet, so there is nothing to sign in to.
  configured: boolean;
  signedIn: boolean;
  // Who this browser is signed in as. Null when it isn't, or when the backend asks for no sign-in.
  email: string | null;
  // What other people see of this user, on their public decks. Null until they choose one.
  username: string | null;
};

let state: AuthState = { checked: false, unreachable: false, required: false, configured: true, signedIn: false, email: null, username: null };
const listeners = new Set<() => void>();

function set(next: Partial<AuthState>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

export function useAuth(): AuthState {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => state,
  );
}

export async function refreshAuth(): Promise<void> {
  set({ checked: false });
  const status = await getAuthStatus();
  if (!status) {
    set({ checked: true, unreachable: true });
    return;
  }
  set({ checked: true, unreachable: false, required: status.required, configured: status.configured, signedIn: status.signed_in, email: status.email, username: status.username ?? null });
}

// Null once signed in, otherwise what to tell the person.
export async function signIn(email: string, password: string): Promise<string | null> {
  const result = await logIn(email, password);
  if ("error" in result) return result.error;
  set({ signedIn: true, email: result.email, username: result.username });
  return null;
}

// The username the backend saved, once the profile page has set it.
export function usernameChanged(username: string): void {
  set({ username });
}

export async function signOut(): Promise<void> {
  await logOut();
  set({ signedIn: false, email: null, username: null });
}

// The backend refused a request: the session ended, or the user was signed out everywhere.
onUnauthorized(() => {
  if (state.required) set({ signedIn: false, email: null, username: null });
});
