import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { listDecks, scryfallManaSymbolUrl, scryfallSets, type Deck, type ScryfallSet } from "./api";
import ManaPips from "./ManaPips";
import { buildScryfallQuery, EMPTY_FILTERS, hasAnyFilter, type ColorMode, type SearchFilters } from "./searchQuery";
import { buttonStyle, eyebrowStyle, inputStyle } from "./styles";

const COLORS = ["W", "U", "B", "R", "G", "C"];

function ColorPips({ selected, onToggle }: { selected: string[]; onToggle: (c: string) => void }) {
  return (
    <div style={{ display: "flex", gap: 6 }}>
      {COLORS.map((c) => (
        <button
          key={c}
          type="button"
          onClick={() => onToggle(c)}
          className="btn"
          style={{
            ...buttonStyle,
            width: 30,
            height: 30,
            padding: 0,
            borderRadius: "50%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            ...(selected.includes(c) ? { borderColor: "var(--accent)" } : {}),
          }}
        >
          <img src={scryfallManaSymbolUrl(c)} alt={c} style={{ width: 16, height: 16 }} />
        </button>
      ))}
    </div>
  );
}

function ModeToggle({
  value,
  onChange,
  options,
}: {
  value: ColorMode;
  onChange: (m: ColorMode) => void;
  options: { mode: ColorMode; label: string }[];
}) {
  return (
    <div style={{ display: "flex", gap: 6 }}>
      {options.map((o) => (
        <button
          key={o.mode}
          type="button"
          onClick={() => onChange(o.mode)}
          className="btn"
          style={
            value === o.mode ? { ...buttonStyle, borderColor: "var(--accent)", color: "var(--accent)" } : buttonStyle
          }
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function CardSearchPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [decks, setDecks] = useState<Deck[]>([]);
  const [targetDeckId, setTargetDeckId] = useState(searchParams.get("deck") ?? "");
  const [showIllegal, setShowIllegal] = useState(false);
  const [onlyCollection, setOnlyCollection] = useState(searchParams.get("collection") === "1");
  const [filters, setFilters] = useState<SearchFilters>(EMPTY_FILTERS);
  const [sets, setSets] = useState<ScryfallSet[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDecks().then(setDecks);
    scryfallSets().then(setSets);
  }, []);

  const targetDeck = decks.find((d) => d.id === targetDeckId) ?? null;

  function updateFilter<K extends keyof SearchFilters>(key: K, value: SearchFilters[K]) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  function toggleColor(list: "colors" | "identity", c: string) {
    setFilters((prev) => {
      const current = prev[list];
      const next = current.includes(c) ? current.filter((x) => x !== c) : [...current, c];
      return { ...prev, [list]: next };
    });
  }

  function useCommanderColors() {
    if (!targetDeck) return;
    setFilters((prev) => ({ ...prev, identity: targetDeck.commander_color_identity, identityMode: "at-most" }));
  }

  function handleSearch() {
    // Checking "only my collection" alone is a real, bounded search (your
    // collection is a finite named set) — unlike the alchemy exclusion,
    // which stays outside hasAnyFilter because "everything except
    // Alchemy" is still unbounded.
    if (!hasAnyFilter(filters) && !onlyCollection) {
      setError("Enter at least one filter to search.");
      return;
    }
    setError(null);
    const query = buildScryfallQuery(filters);
    const params = new URLSearchParams({ q: query, page: "1" });
    if (targetDeckId) params.set("deck", targetDeckId);
    if (showIllegal) params.set("showIllegal", "1");
    if (onlyCollection) params.set("collection", "1");
    navigate(`/search/results?${params.toString()}`);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <header>
        <Link to="/" style={{ ...eyebrowStyle, textDecoration: "none", display: "inline-block" }}>
          &larr; ALL DECKS
        </Link>
        <div style={{ fontSize: 26, fontWeight: 600, marginTop: 4 }}>Search cards</div>
      </header>

      <div style={{ maxWidth: 420, display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <div style={eyebrowStyle}>ADD TO DECK</div>
          <select
            value={targetDeckId}
            onChange={(e) => setTargetDeckId(e.target.value)}
            style={{ ...inputStyle, width: "100%" }}
          >
            <option value="">Browse only (pick later)</option>
            {decks.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name ?? d.commander ?? "Untitled deck"}
              </option>
            ))}
          </select>
          {targetDeck && targetDeck.commander_color_identity.length > 0 && (
            <div style={{ marginTop: 6 }}>
              <ManaPips colors={targetDeck.commander_color_identity} />
            </div>
          )}
          {targetDeck && (
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, marginTop: 8 }}>
              <input type="checkbox" checked={showIllegal} onChange={(e) => setShowIllegal(e.target.checked)} />
              Show cards that don't fit this deck
            </label>
          )}
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, marginTop: 8 }}>
            <input
              type="checkbox"
              checked={onlyCollection}
              onChange={(e) => setOnlyCollection(e.target.checked)}
            />
            Only cards I own
          </label>
        </div>

        <div>
          <div style={eyebrowStyle}>NAME</div>
          <input
            value={filters.name}
            onChange={(e) => updateFilter("name", e.target.value)}
            placeholder="Card name contains…"
            style={{ ...inputStyle, width: "100%" }}
          />
        </div>

        <div>
          <div style={eyebrowStyle}>COLOR</div>
          <ColorPips selected={filters.colors} onToggle={(c) => toggleColor("colors", c)} />
          <div style={{ marginTop: 6 }}>
            <ModeToggle
              value={filters.colorMode}
              onChange={(m) => updateFilter("colorMode", m)}
              options={[
                { mode: "at-least", label: "At least" },
                { mode: "exact", label: "Exactly" },
              ]}
            />
          </div>
        </div>

        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={eyebrowStyle}>COLOR IDENTITY</div>
            {targetDeck?.commander && (
              <button
                type="button"
                onClick={useCommanderColors}
                className="btn"
                style={{ ...buttonStyle, fontSize: 11, padding: "2px 8px" }}
              >
                Use commander's
              </button>
            )}
          </div>
          <ColorPips selected={filters.identity} onToggle={(c) => toggleColor("identity", c)} />
          <div style={{ marginTop: 6 }}>
            <ModeToggle
              value={filters.identityMode}
              onChange={(m) => updateFilter("identityMode", m)}
              options={[
                { mode: "at-most", label: "Within these" },
                { mode: "exact", label: "Exactly" },
              ]}
            />
          </div>
        </div>

        <div>
          <div style={eyebrowStyle}>MANA VALUE</div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="number"
              min={0}
              value={filters.cmcMin}
              onChange={(e) => updateFilter("cmcMin", e.target.value)}
              placeholder="Min"
              style={{ ...inputStyle, width: 70 }}
            />
            <span>–</span>
            <input
              type="number"
              min={0}
              value={filters.cmcMax}
              onChange={(e) => updateFilter("cmcMax", e.target.value)}
              placeholder="Max"
              style={{ ...inputStyle, width: 70 }}
            />
          </div>
        </div>

        <div>
          <div style={eyebrowStyle}>TYPE / SUBTYPE</div>
          <input
            value={filters.subtype}
            onChange={(e) => updateFilter("subtype", e.target.value)}
            placeholder="e.g. Dragon, Equipment…"
            style={{ ...inputStyle, width: "100%" }}
          />
        </div>

        <div>
          <div style={eyebrowStyle}>RULES TEXT</div>
          <input
            value={filters.oracleText}
            onChange={(e) => updateFilter("oracleText", e.target.value)}
            placeholder="e.g. draw a card"
            style={{ ...inputStyle, width: "100%" }}
          />
        </div>

        <div>
          <div style={eyebrowStyle}>SET</div>
          <select
            value={filters.set}
            onChange={(e) => updateFilter("set", e.target.value)}
            style={{ ...inputStyle, width: "100%" }}
          >
            <option value="">Any set</option>
            {sets.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </select>
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
          <input
            type="checkbox"
            checked={filters.includeAlchemy}
            onChange={(e) => updateFilter("includeAlchemy", e.target.checked)}
          />
          Include Alchemy cards
        </label>

        <button onClick={handleSearch} className="btn" style={buttonStyle}>
          Search
        </button>
        {error && <div style={{ color: "var(--danger)", fontSize: 13 }}>{error}</div>}
      </div>
    </div>
  );
}
