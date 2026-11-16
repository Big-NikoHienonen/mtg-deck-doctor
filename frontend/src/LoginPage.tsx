import { useState, type FormEvent, type KeyboardEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { BackendDown } from "./AuthCards";
import { signIn, useAuth } from "./authStore";
import Logo from "./Logo";
import "./login.css";

// Where to go after signing in: the page the person was on when they chose Sign in, if it is a page
// of this app, and the landing page otherwise.
function returnPath(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from;
  return typeof from === "string" && from.startsWith("/") && !from.startsWith("//") && !from.startsWith("/login") ? from : "/";
}

// The sign-in page. Signing in changes what the app shows (see authStore.ts), so a success leaves
// nothing to do but go back to where the person was, and only a failure is shown here.
export default function LoginPage() {
  const auth = useAuth();
  const { state } = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  if (!auth.checked) return null;
  if (auth.unreachable) return <BackendDown />;
  if (!auth.required || auth.signedIn) return <Navigate to={returnPath(state)} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password || busy) return;
    setBusy(true);
    setProblem(null);
    const result = await signIn(email, password);
    if (result !== null) {
      setProblem(result);
      setBusy(false);
    }
  }

  function trackCapsLock(e: KeyboardEvent) {
    setCapsLock(e.getModifierState("CapsLock"));
  }

  return (
    <div className="login">
      <div className="login-brand">
        <Logo size={56} />
        <div className="login-name">MTG Deck Doctor</div>
      </div>

      <form className="login-card" onSubmit={submit}>
        <h1>Sign in</h1>
        <p className="login-lede">Sign in to build and edit your decks.</p>

        <div className="login-field">
          <label htmlFor="login-email">Email</label>
          <div className="login-input" data-invalid={problem !== null}>
            <input
              id="login-email"
              type="email"
              name="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              inputMode="email"
              autoCapitalize="none"
              spellCheck={false}
              autoFocus
              maxLength={254}
              aria-invalid={problem !== null}
              aria-describedby={problem ? "login-error" : undefined}
            />
          </div>
        </div>

        <div className="login-field">
          <label htmlFor="login-password">Password</label>
          <div className="login-input" data-invalid={problem !== null}>
            <input
              id="login-password"
              type={reveal ? "text" : "password"}
              name="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={trackCapsLock}
              onKeyUp={trackCapsLock}
              autoComplete="current-password"
              maxLength={200}
              aria-invalid={problem !== null}
              aria-describedby={problem ? "login-error" : undefined}
            />
            <button type="button" className="login-toggle" onClick={() => setReveal((r) => !r)} aria-pressed={reveal} aria-label="Show password">
              {reveal ? "Hide" : "Show"}
            </button>
          </div>
          {capsLock && <p className="login-hint">Caps Lock is on.</p>}
        </div>

        {problem && (
          <p id="login-error" className="login-error" role="alert">
            {problem}
          </p>
        )}

        <button type="submit" className="login-submit" disabled={busy || !email.trim() || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="login-foot">Looking at someone's deck? Open the link they sent you. You don't need to sign in.</p>
    </div>
  );
}
