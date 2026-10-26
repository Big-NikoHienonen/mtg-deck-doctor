import type { CSSProperties } from "react";

export const eyebrowStyle: CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: "0.1em",
  color: "var(--accent)",
  marginBottom: 8,
};

// Rest-state background/color/border live in the .btn CSS class (index.css),
// not here — inline styles always beat a stylesheet rule for the same
// property, hover and active states included, so anything that needs to
// visibly change on :hover/:active can't also be set inline. Always pair
// this with className="btn" (or "btn btn-danger" for destructive actions).
export const buttonStyle: CSSProperties = {
  fontFamily: "inherit",
  fontSize: 14,
  padding: "8px 14px",
  borderRadius: 4,
  cursor: "pointer",
};

export const inputStyle: CSSProperties = {
  flexGrow: 1,
  fontFamily: "inherit",
  fontSize: 15,
  padding: "10px 14px",
  background: "var(--surface)",
  color: "var(--text)",
  border: "1px solid var(--border)",
  borderRadius: 4,
};
