import { useEffect } from "react";
import SignInForm from "./SignInForm";
import { buttonStyle } from "./styles";

// The password form in a window over a page, for the person looking at a deck who owns it. Signing in
// swaps the page for the owner's, which closes this.
export default function SignInModal({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(20, 14, 8, 0.55)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24, zIndex: 100 }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Sign in"
        onClick={(e) => e.stopPropagation()}
        style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, width: "100%", maxWidth: 380, padding: 24, display: "flex", flexDirection: "column", gap: 14 }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 18, fontWeight: 600 }}>Sign in to edit</div>
          <button onClick={onClose} aria-label="Close" className="btn" style={{ ...buttonStyle, padding: "4px 10px" }}>
            &times;
          </button>
        </div>
        <SignInForm />
      </div>
    </div>
  );
}
