import { useState, type FormEvent } from "react";
import { signIn } from "./authStore";
import { buttonStyle, inputStyle } from "./styles";

// The password form. Signing in changes what the app shows (see authStore.ts), so a success leaves
// nothing to do here, and only a failure is shown.
export default function SignInForm() {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setProblem(null);
    const result = await signIn(password);
    if (result !== null) {
      setProblem(result);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        aria-label="Password"
        placeholder="Password"
        autoComplete="current-password"
        autoFocus
        maxLength={200}
        style={{ ...inputStyle, flexGrow: 0 }}
      />
      {problem && (
        <div role="alert" style={{ fontSize: 14, color: "var(--danger)" }}>
          {problem}
        </div>
      )}
      <button type="submit" className="btn" disabled={busy || !password} style={buttonStyle}>
        {busy ? "…" : "Sign in"}
      </button>
    </form>
  );
}
