import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createDeck, scryfallSearchCards, type SearchCard } from "./api";
import CardImage from "./CardImage";
import ManaPips from "./ManaPips";
import "./newdeck.css";

// Searches Scryfall for commanders whose names contain every word typed.
function commanderQuery(text: string): string {
  const words = text.replace(/["\\]/g, "").split(/\s+/).filter(Boolean);
  return `${words.map((w) => `name:"${w}"`).join(" ")} is:commander legal:commander`;
}

// "New deck": a name and a commander, then straight to the deck. Both are optional: a deck without a
// commander asks for one on its own page, and one without a name is called after its commander.
export default function NewDeckModal({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const ids = useId();
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchCard[]>([]);
  const [searching, setSearching] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  const [commander, setCommander] = useState<SearchCard | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => e.key === "Escape" && !creating && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, creating]);

  // Searches a moment after the typing stops, and ignores an answer that a newer search has replaced.
  useEffect(() => {
    const text = query.trim();
    if (commander || text.length < 2) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    let stale = false;
    const timer = window.setTimeout(async () => {
      try {
        const found = await scryfallSearchCards(commanderQuery(text), 1);
        if (!stale) {
          setResults(found.cards.slice(0, 8));
          setHighlighted(0);
        }
      } catch {
        if (!stale) setResults([]);
      } finally {
        if (!stale) setSearching(false);
      }
    }, 250);
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
  }, [query, commander]);

  function choose(card: SearchCard) {
    setCommander(card);
    setQuery("");
    setResults([]);
    setError(null);
  }

  function clearCommander() {
    setCommander(null);
    window.setTimeout(() => searchRef.current?.focus(), 0);
  }

  function onSearchKey(e: KeyboardEvent<HTMLInputElement>) {
    if (results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(results[highlighted]);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (creating) return;
    setCreating(true);
    setError(null);
    try {
      const deck = await createDeck({ name: name.trim(), commander: commander?.name ?? "" });
      navigate(`/decks/${deck.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't create the deck.");
      setCreating(false);
    }
  }

  const listId = `${ids}-results`;
  const showList = !commander && query.trim().length >= 2;

  return (
    <div className="nd-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !creating && onClose()}>
      <form className="nd-dialog" role="dialog" aria-modal="true" aria-labelledby={`${ids}-title`} onSubmit={submit}>
        <div className="nd-head">
          <h2 id={`${ids}-title`}>New deck</h2>
          <button type="button" className="nd-x" aria-label="Close" onClick={onClose} disabled={creating}>
            ×
          </button>
        </div>

        <label className="nd-field" htmlFor={`${ids}-name`}>
          <span>Deck name</span>
          <input id={`${ids}-name`} value={name} maxLength={100} autoFocus onChange={(e) => setName(e.target.value)} placeholder={commander ? commander.name : "Name your deck"} autoComplete="off" />
          <small>{commander ? "Leave it blank to call the deck by its commander." : "You can rename it any time."}</small>
        </label>

        <div className="nd-field">
          <label htmlFor={`${ids}-search`}>Commander</label>
          {commander ? (
            <div className="nd-chosen">
              <CardImage cardId={commander.id} version="normal" alt={commander.name} className="nd-art" />
              <div className="nd-chosen-text">
                <strong>{commander.name}</strong>
                <span>{commander.typeLine}</span>
                <ManaPips colors={commander.colorIdentity} size={16} />
                <button type="button" className="nd-link" onClick={clearCommander}>
                  Choose a different commander
                </button>
              </div>
            </div>
          ) : (
            <>
              <input
                id={`${ids}-search`}
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onSearchKey}
                placeholder="Search for a commander…"
                autoComplete="off"
                role="combobox"
                aria-expanded={showList && results.length > 0}
                aria-controls={listId}
                aria-activedescendant={results[highlighted] ? `${ids}-opt-${highlighted}` : undefined}
              />
              {showList && (
                <ul id={listId} className="nd-results" role="listbox">
                  {results.map((card, i) => (
                    <li key={card.id} id={`${ids}-opt-${i}`} role="option" aria-selected={i === highlighted} onMouseEnter={() => setHighlighted(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => choose(card)}>
                      <CardImage cardId={card.id} version="small" alt="" className="nd-thumb" loading="lazy" />
                      <span className="nd-result-text">
                        <strong>{card.name}</strong>
                        <span>{card.typeLine}</span>
                      </span>
                      <ManaPips colors={card.colorIdentity} size={14} />
                    </li>
                  ))}
                  {results.length === 0 && <li className="nd-empty">{searching ? "Searching…" : "No legal commanders match that."}</li>}
                </ul>
              )}
              <small>Optional. A deck without one asks for it on its own page.</small>
            </>
          )}
        </div>

        {error && (
          <div className="nd-error" role="alert">
            {error}
          </div>
        )}

        <div className="nd-actions">
          <button type="button" className="nd-cancel" onClick={onClose} disabled={creating}>
            Cancel
          </button>
          <button type="submit" className="nd-create" disabled={creating}>
            {creating ? "Creating…" : "Create deck"}
          </button>
        </div>
      </form>
    </div>
  );
}
