import type { ReactNode } from "react";
import { refreshAuth } from "./authStore";
import { buttonStyle } from "./styles";

export function Note({ children }: { children: ReactNode }) {
  return <p style={{ margin: 0, fontSize: 14, lineHeight: 1.5, color: "var(--text-muted)" }}>{children}</p>;
}

// A small centered card, for a page that has one thing to say.
export function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ maxWidth: 380, margin: "80px auto 0", padding: 24, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, display: "flex", flexDirection: "column", gap: 14 }}>
      <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>{title}</h1>
      {children}
    </div>
  );
}

export function BackendDown() {
  return (
    <Card title="Can't reach the backend">
      <Note>Is it running on port 8000?</Note>
      <button type="button" className="btn" style={buttonStyle} onClick={() => refreshAuth()}>
        Try again
      </button>
    </Card>
  );
}
