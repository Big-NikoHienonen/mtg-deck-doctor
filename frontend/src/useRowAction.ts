import { useState } from "react";

// Tracks one in-flight action per row (keyed by whatever identifies the
// row) and the last error for each, so a failed swap shows its message on
// the row that failed instead of in a shared banner.
export function useRowAction() {
  const [pending, setPending] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function run(rowKey: string, action: () => Promise<void>) {
    setPending(rowKey);
    setErrors((prev) => ({ ...prev, [rowKey]: "" }));
    try {
      await action();
    } catch (err) {
      setErrors((prev) => ({ ...prev, [rowKey]: err instanceof Error ? err.message : "That didn't work." }));
    } finally {
      setPending(null);
    }
  }

  return { pending, errors, run };
}
