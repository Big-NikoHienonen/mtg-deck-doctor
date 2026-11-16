import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { listPublicDecks, scryfallImageUrlById, type PublicDeckSummary } from "./api";
import ManaPips from "./ManaPips";
import { relativeTime } from "./relativeTime";
import { buttonStyle } from "./styles";
import "./browse.css";

const PAGE_SIZE = 24;

type Sort = "updated" | "name";

// Browse: the decks people have made public, open to anyone without signing in. Search looks in a deck's
// title, its commander and its builder's username. A tile opens the deck's page.
export default function BrowsePage() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<Sort>("updated");
  const [decks, setDecks] = useState<PublicDeckSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Counts requests, so an answer to one that a newer search has replaced is thrown away.
  const latest = useRef(0);

  // Searches a moment after the typing stops.
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  const load = useCallback(
    async (offset: number) => {
      const mine = ++latest.current;
      setLoading(true);
      setError(null);
      try {
        const page = await listPublicDecks({ q: search, sort, limit: PAGE_SIZE, offset });
        if (mine !== latest.current) return;
        setDecks((current) => (offset === 0 ? page.decks : [...current, ...page.decks]));
        setTotal(page.total);
      } catch (err) {
        if (mine === latest.current) setError(err instanceof Error ? err.message : "Couldn't load the decks.");
      } finally {
        if (mine === latest.current) setLoading(false);
      }
    },
    [search, sort],
  );

  useEffect(() => {
    load(0);
  }, [load]);

  return (
    <div className="browse">
      <header className="browse-head">
        <h1>Browse decks</h1>
        <p>Commander decks other people have built. Open one to see the whole list.</p>
      </header>

      <div className="browse-controls">
        <input
          type="search"
          className="browse-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by deck, commander or builder…"
          aria-label="Search decks"
          maxLength={100}
          autoComplete="off"
        />
        <label className="browse-sort">
          <span>Sort by</span>
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="updated">Newest</option>
            <option value="name">Name</option>
          </select>
        </label>
      </div>

      {error && (
        <div className="browse-error" role="alert">
          {error}{" "}
          <button type="button" className="btn" style={buttonStyle} onClick={() => load(0)}>
            Try again
          </button>
        </div>
      )}

      {!error && !loading && decks.length === 0 && (
        <div className="browse-empty">{search.trim() ? "No decks match that search." : "No one has made a deck public yet."}</div>
      )}

      {decks.length > 0 && (
        <>
          <div className="browse-count">
            {total} deck{total === 1 ? "" : "s"}
          </div>
          <div className="browse-grid">
            {decks.map((deck) => (
              <PublicDeckTile key={deck.id} deck={deck} />
            ))}
          </div>
        </>
      )}

      {loading && <div className="browse-empty">Loading…</div>}

      {!loading && !error && decks.length < total && (
        <button type="button" className="btn browse-more" style={buttonStyle} onClick={() => load(decks.length)}>
          Show more
        </button>
      )}
    </div>
  );
}

function PublicDeckTile({ deck }: { deck: PublicDeckSummary }) {
  return (
    <Link to={`/decks/${deck.id}`} className="browse-tile">
      <div className="browse-art">
        {deck.commander_id && <img src={scryfallImageUrlById(deck.commander_id, "art_crop")} alt="" loading="lazy" />}
      </div>
      <div className="browse-body">
        <div className="browse-title">{deck.title}</div>
        {deck.commander !== deck.title && <div className="browse-commander">{deck.commander}</div>}
        <div className="browse-meta">
          <ManaPips colors={deck.color_identity} size={14} />
          <span>
            {deck.card_count}/100 · ${Math.round(deck.price_usd)}
          </span>
        </div>
        <div className="browse-by">
          {deck.owner_name ? (
            <>
              by <strong>{deck.owner_name}</strong>
            </>
          ) : (
            "by an anonymous builder"
          )}
          <span> · {relativeTime(deck.updated_at)}</span>
        </div>
      </div>
    </Link>
  );
}
