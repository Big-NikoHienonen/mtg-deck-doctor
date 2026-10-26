import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { scryfallAutocomplete } from "./api";
import { buttonStyle, inputStyle } from "./styles";

type Props = {
  placeholder: string;
  submitLabel: string;
  onSubmit: (name: string) => Promise<void>;
};

export default function CardSearchBox({ placeholder, submitLabel, onSubmit }: Props) {
  const [value, setValue] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [highlighted, setHighlighted] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    if (!value.trim()) {
      setSuggestions([]);
      return;
    }
    debounceRef.current = window.setTimeout(() => {
      scryfallAutocomplete(value).then((found) => {
        setSuggestions(found);
        setHighlighted(0); // a fresh result list always starts with the first option selected
      });
    }, 200);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [value]);

  async function submit(name: string) {
    if (!name.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(name.trim());
      setValue("");
      setSuggestions([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work.");
    } finally {
      setSubmitting(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      submit(suggestions[highlighted]);
    } else if (e.key === "Escape") {
      setSuggestions([]);
    }
  }

  return (
    <div style={{ position: "relative" }}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(value);
        }}
        style={{ display: "flex", gap: 8 }}
      >
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          style={inputStyle}
          disabled={submitting}
        />
        <button type="submit" className="btn" style={buttonStyle} disabled={submitting || !value.trim()}>
          {submitLabel}
        </button>
      </form>

      {suggestions.length > 0 && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            zIndex: 10,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            marginTop: 4,
            maxHeight: 220,
            overflowY: "auto",
          }}
        >
          {suggestions.map((name, i) => (
            <div
              key={name}
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => setHighlighted(i)}
              onClick={() => submit(name)}
              style={{
                padding: "8px 12px",
                fontSize: 14,
                cursor: "pointer",
                background: i === highlighted ? "var(--user-bubble)" : "transparent",
                borderBottom: i < suggestions.length - 1 ? "1px solid var(--border)" : "none",
              }}
            >
              {name}
            </div>
          ))}
        </div>
      )}

      {error && <div style={{ color: "var(--accent)", fontSize: 13, marginTop: 6 }}>{error}</div>}
    </div>
  );
}
