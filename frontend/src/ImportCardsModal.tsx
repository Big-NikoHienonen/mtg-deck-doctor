import { useEffect, useState } from "react";
import { getCardInfoBatch, importCards, type CardInfo, type Deck } from "./api";
import { parseDecklist, type ParsedImportLine } from "./importExport";
import { buttonStyle, inputStyle } from "./styles";

const overlayStyle = {
  position: "fixed",
  inset: 0,
  background: "rgba(20, 14, 8, 0.55)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 24,
  zIndex: 100,
} as const;

const panelStyle = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 10,
  width: "100%",
  maxWidth: 560,
  maxHeight: "85vh",
  overflow: "auto",
  padding: 24,
  display: "flex",
  flexDirection: "column" as const,
  gap: 12,
};

// Two steps: paste text, then review what resolved before anything is
// actually added — never silently drops a line the user hasn't seen.
export default function ImportCardsModal({
  deckId,
  existingNames,
  onImported,
  onBusyChange,
  onClose,
}: {
  deckId: string;
  // Names already in the deck (cards + commander) — a line matching one
  // of these is already a confirmed-valid card by construction (it only
  // got into the deck through real validation in the first place), so
  // there's no reason to spend a throttled Scryfall request re-checking
  // it. Still flows through to the actual import attempt afterward
  // unchanged — a basic land here should still be addable (not singleton-
  // restricted), and a non-basic will get the usual duplicate rejection
  // from the backend's real validation, same as any other repeat add.
  existingNames: Set<string>;
  // Hands over the card data fetched to check the names, so the page that
  // opened this doesn't ask for the same cards a second time.
  onImported: (deck: Deck, cardInfo: Record<string, CardInfo>) => void;
  // True from the moment a check or import starts until it finishes (or
  // this closes). The page holds off its own background lookups for that
  // long, so nothing competes with the import for Scryfall.
  onBusyChange: (busy: boolean) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const [step, setStep] = useState<"editing" | "reviewing">("editing");
  const [parsed, setParsed] = useState<ParsedImportLine[]>([]);
  const [alreadyInDeckCount, setAlreadyInDeckCount] = useState(0);
  // Confirmed Scryfall 404s — a real typo, needs the text fixed. Kept
  // separate from "failed" (a lookup attempt simply didn't succeed,
  // almost always the rate limit on a big fresh batch) — conflating the
  // two would show a transient failure as "this isn't a real card",
  // which is exactly the bug a 100-card Moxfield import surfaced.
  const [notFound, setNotFound] = useState<Set<string>>(new Set());
  const [failed, setFailed] = useState<Set<string>>(new Set());
  const [parsing, setParsing] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [resolvedInfo, setResolvedInfo] = useState<Record<string, CardInfo>>({});

  const busy = parsing || retrying || importing;
  useEffect(() => {
    onBusyChange(busy);
  }, [busy, onBusyChange]);
  useEffect(() => () => onBusyChange(false), [onBusyChange]);

  async function handleParse() {
    setParsing(true);
    const parsedLines = parseDecklist(text);
    const toCheck = parsedLines.filter((p) => !existingNames.has(p.rawName)).map((p) => p.rawName);
    const resolution = await getCardInfoBatch(toCheck);
    setParsed(parsedLines);
    setResolvedInfo(resolution.info);
    setAlreadyInDeckCount(parsedLines.length - toCheck.length);
    setNotFound(new Set(resolution.notFound));
    setFailed(new Set(resolution.failed));
    setResult(null);
    setStep("reviewing");
    setParsing(false);
  }

  async function handleRetryFailed() {
    setRetrying(true);
    const stillFailing = parsed.filter((p) => failed.has(p.rawName)).map((p) => p.rawName);
    const resolution = await getCardInfoBatch(stillFailing);
    setResolvedInfo((prev) => ({ ...prev, ...resolution.info }));
    setNotFound((prev) => new Set([...prev, ...resolution.notFound]));
    setFailed(new Set(resolution.failed));
    setRetrying(false);
  }

  async function handleImport() {
    setImporting(true);
    try {
      const outcome = await importCards(deckId, resolvedEntries);
      onImported(outcome.deck, resolvedInfo);
      setResult(
        outcome.failed.length > 0
          ? `Added ${outcome.added}. ${outcome.failed.length} rejected — e.g. ${outcome.failed[0].name}: ${outcome.failed[0].error}`
          : `Added ${outcome.added} card${outcome.added === 1 ? "" : "s"}.`,
      );
    } catch (err) {
      setResult(err instanceof Error ? err.message : "That didn't work.");
    } finally {
      setImporting(false);
    }
  }

  const resolvedEntries = parsed
    .filter((p) => !notFound.has(p.rawName) && !failed.has(p.rawName))
    .map((p) => ({ name: p.rawName, quantity: p.quantity }));
  const notFoundNames = parsed.filter((p) => notFound.has(p.rawName)).map((p) => p.rawName);
  const failedNames = parsed.filter((p) => failed.has(p.rawName)).map((p) => p.rawName);
  const totalQuantity = resolvedEntries.reduce((sum, r) => sum + r.quantity, 0);

  return (
    <div onClick={onClose} style={overlayStyle}>
      <div onClick={(e) => e.stopPropagation()} style={panelStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 18, fontWeight: 600 }}>Import cards</div>
          <button onClick={onClose} aria-label="Close" className="btn" style={{ ...buttonStyle, padding: "4px 10px" }}>
            &times;
          </button>
        </div>

        {step === "editing" && (
          <>
            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
              Paste a decklist — one card per line, like "1 Sol Ring" or "4x Mountain". Other lines (category
              headers, set codes, "Commander: …") are ignored.
            </div>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={"1 Sol Ring\n1 Command Tower\n4 Mountain"}
              rows={12}
              style={{ ...inputStyle, width: "100%", fontFamily: "monospace", resize: "vertical" }}
            />
            <button onClick={handleParse} disabled={parsing || !text.trim()} className="btn" style={buttonStyle}>
              {parsing ? "Checking cards…" : "Review import"}
            </button>
          </>
        )}

        {step === "reviewing" && (
          <>
            <div style={{ fontSize: 14 }}>
              {totalQuantity} card{totalQuantity === 1 ? "" : "s"} ready to add ({resolvedEntries.length} unique
              name{resolvedEntries.length === 1 ? "" : "s"}).
            </div>
            {alreadyInDeckCount > 0 && (
              <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
                {alreadyInDeckCount} already in this deck — skipped the Scryfall check for those (basic lands
                among them can still be added again; anything else will just be rejected as a duplicate, same as
                adding it by hand).
              </div>
            )}
            {failedNames.length > 0 && (
              <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
                {failedNames.length} card{failedNames.length === 1 ? "" : "s"} couldn't be checked right now
                (Scryfall is likely rate-limited) — not confirmed wrong, just unverified so far:
                <ul style={{ margin: "6px 0 0", paddingLeft: 20 }}>
                  {failedNames.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
                <button
                  onClick={handleRetryFailed}
                  disabled={retrying}
                  className="btn"
                  style={{ ...buttonStyle, marginTop: 6 }}
                >
                  {retrying ? "Checking…" : `Check ${failedNames.length} again`}
                </button>
              </div>
            )}
            {notFoundNames.length > 0 && (
              <div style={{ fontSize: 13, color: "var(--danger)" }}>
                {notFoundNames.length} line{notFoundNames.length === 1 ? "" : "s"} couldn't be matched to a real
                card and won't be imported — fix the text and review again, or continue without{" "}
                {notFoundNames.length === 1 ? "it" : "them"}:
                <ul style={{ margin: "6px 0 0", paddingLeft: 20 }}>
                  {notFoundNames.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              </div>
            )}
            {result && <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{result}</div>}
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={() => setStep("editing")} className="btn" style={buttonStyle}>
                ← Edit
              </button>
              <button
                onClick={handleImport}
                disabled={importing || resolvedEntries.length === 0}
                className="btn"
                style={buttonStyle}
              >
                {importing ? "Importing…" : `Import ${totalQuantity} card${totalQuantity === 1 ? "" : "s"}`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
