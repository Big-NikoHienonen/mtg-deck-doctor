import { useCallback, useEffect, useState } from "react";
import { getHub, type Hub } from "./api";

// What the landing page and the decks page both draw on: loaded when the page opens, and again when
// something on it changes what the backend knows (load).
export function useHub() {
  const [hub, setHub] = useState<Hub | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setHub(await getHub());
      setError(null);
    } catch {
      setError("Couldn't reach the Deck Doctor backend. Is it running on port 8000?");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { hub, setHub, error, load };
}
