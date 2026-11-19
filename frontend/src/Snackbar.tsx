import { useEffect } from "react";
import { dismissSnackbar, useSnackbar } from "./snackbarStore";
import "./snackbar.css";

// How long a message stays: long enough to read a sentence about why something failed.
const SHOWN_MS = 7000;

// Draws the message in snackbarStore.ts. Mounted once, in App. The live region is always in the page, so a
// screen reader announces a message that appears in it.
export default function Snackbar() {
  const snack = useSnackbar();

  useEffect(() => {
    if (!snack) return;
    const timer = window.setTimeout(() => dismissSnackbar(snack.id), SHOWN_MS);
    return () => window.clearTimeout(timer);
  }, [snack]);

  return (
    <div className="snackbar-host" role="alert" aria-live="assertive" aria-atomic="true">
      {snack && (
        <div className="snackbar" key={snack.id}>
          <span className="snackbar-message">{snack.message}</span>
          <button type="button" className="snackbar-close" aria-label="Dismiss" onClick={() => dismissSnackbar(snack.id)}>
            ×
          </button>
        </div>
      )}
    </div>
  );
}
