import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { saveUsername } from "./api";
import { useAuth, usernameChanged } from "./authStore";
import "./login.css";

// Your profile: the email you sign in with, which only you see, and the username other people see beside
// the decks you make public. Until you pick one, your public decks show without a name.
export default function ProfilePage() {
  const auth = useAuth();
  const [username, setUsername] = useState(auth.username ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  if (!auth.required) {
    return (
      <div className="login">
        <div className="login-card">
          <h1>Your profile</h1>
          <p className="login-lede">This server runs without sign-in, so there is no account to give a username to.</p>
        </div>
      </div>
    );
  }

  const unchanged = username.trim() === (auth.username ?? "");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || unchanged) return;
    setBusy(true);
    setProblem(null);
    setSaved(false);
    try {
      usernameChanged(await saveUsername(username.trim()));
      setSaved(true);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "Couldn't save that username.");
    }
    setBusy(false);
  }

  return (
    <div className="login">
      <form className="login-card" onSubmit={submit}>
        <h1>Your profile</h1>
        <p className="login-lede">
          Your username is what other people see beside your public decks. Your email is never shown to anyone.{" "}
          {auth.username === null && "Until you choose a username, your public decks show without a name."}
        </p>

        <div className="login-field">
          <label htmlFor="profile-email">Email</label>
          <div className="login-input">
            <input id="profile-email" value={auth.email ?? ""} readOnly aria-readonly="true" />
          </div>
        </div>

        <div className="login-field">
          <label htmlFor="profile-username">Username</label>
          <div className="login-input" data-invalid={problem !== null}>
            <input
              id="profile-username"
              value={username}
              onChange={(e) => {
                setUsername(e.target.value);
                setSaved(false);
              }}
              autoComplete="nickname"
              autoCapitalize="none"
              spellCheck={false}
              maxLength={24}
              aria-invalid={problem !== null}
              aria-describedby="profile-username-hint"
            />
          </div>
          <p id="profile-username-hint" className="login-hint">
            3 to 24 characters: letters, numbers, hyphens and underscores.
          </p>
        </div>

        {problem && (
          <p className="login-error" role="alert">
            {problem}
          </p>
        )}
        {saved && (
          <p className="login-hint" role="status">
            Saved. <Link to="/browse">Browse decks</Link>
          </p>
        )}

        <button type="submit" className="login-submit" disabled={busy || unchanged || username.trim().length === 0}>
          {busy ? "Saving…" : "Save username"}
        </button>
      </form>
    </div>
  );
}
