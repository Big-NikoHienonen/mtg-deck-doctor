import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Deck } from "./api";
import ChatSuggestions from "./ChatSuggestions";
import type { ChatItem, Suggestion } from "./chatMessages";
import "./correspondence.css";

// How much of the conversation is on the page at first, and how much more each "Show earlier" brings.
// A long history is thousands of pixels; the part people read is the end.
const FIRST_SHOWN = 12;
const SHOWN_MORE = 20;

// The distance from the bottom of the page, in pixels, within which the page counts as "at the bottom":
// close enough that a new reply should scroll into view rather than wait behind a button.
const NEAR_BOTTOM = 160;

const STARTERS = ["What should I cut from this deck?", "Where is my mana base weakest?", "Suggest some card draw that fits my commander"];

const remarkPlugins = [remarkGfm];

// A table is wider than the column on a phone, so it scrolls sideways inside its own box instead of
// stretching the page.
const markdownComponents = {
  table: ({ children }: { children?: ReactNode }) => (
    <div className="cx-table">
      <table>{children}</table>
    </div>
  ),
  a: ({ href, children }: { href?: string; children?: ReactNode }) => (
    <a href={href} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  ),
};

type Props = {
  deck: Deck;
  items: ChatItem[];
  sending: boolean;
  input: string;
  onInput: (value: string) => void;
  onSend: () => void;
  // The Doctor can't be asked right now: Send waits, and `notice` says why.
  locked: boolean;
  notice: ReactNode;
  onApply: (s: Suggestion) => Promise<void>;
};

const scrollToEnd = (smooth: boolean) => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: smooth ? "smooth" : "auto" });

// The conversation with the Doctor. It opens on the latest message, the box stays at the bottom of the
// screen as the page scrolls, and the box keeps the cursor after a send so a thought can follow a thought.
export default function Correspondence({ deck, items, sending, input, onInput, onSend, locked, notice, onApply }: Props) {
  const [shown, setShown] = useState(FIRST_SHOWN);
  const [nearBottom, setNearBottom] = useState(true);
  const nearBottomRef = useRef(true);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const lastReplyRef = useRef<HTMLDivElement>(null);
  const seenCount = useRef(items.length);
  const heightBeforeEarlier = useRef<number | null>(null);

  const hidden = Math.max(0, items.length - shown);
  const visible = items.slice(hidden);
  const lastRole = items.at(-1)?.role;

  // Opens on the latest message. On a computer the cursor goes to the box too; on a phone it would only
  // bring the keyboard up over the conversation.
  useLayoutEffect(() => {
    scrollToEnd(false);
    if (window.matchMedia("(pointer: fine)").matches) boxRef.current?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    const onScroll = () => {
      const near = document.documentElement.scrollHeight - window.scrollY - window.innerHeight < NEAR_BOTTOM;
      nearBottomRef.current = near;
      setNearBottom(near);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  // Your own message goes to the bottom. The Doctor's reply scrolls to where the reply begins, so a long
  // answer is read from its first line, unless you had scrolled up to read something, in which case the
  // button says there is more below.
  useEffect(() => {
    if (items.length === seenCount.current) return;
    const grew = items.length > seenCount.current;
    seenCount.current = items.length;
    if (!grew) return;
    if (lastRole === "user") scrollToEnd(true);
    else if (nearBottomRef.current) lastReplyRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [items.length, lastRole]);

  // Older messages are added above what is on screen, so the page is moved by the height they add, and the
  // message being read stays where it was.
  useLayoutEffect(() => {
    if (heightBeforeEarlier.current === null) return;
    window.scrollBy(0, document.documentElement.scrollHeight - heightBeforeEarlier.current);
    heightBeforeEarlier.current = null;
  }, [shown]);

  const showEarlier = () => {
    heightBeforeEarlier.current = document.documentElement.scrollHeight;
    setShown((n) => n + SHOWN_MORE);
  };

  // The box grows with what is typed, up to a few lines, and shrinks back when it is emptied.
  const fit = useCallback(() => {
    const box = boxRef.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, 168)}px`;
  }, []);
  useLayoutEffect(fit, [input, fit]);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      onSend();
    }
  }

  const lastAssistant = items.findLastIndex((m) => m.role === "assistant" && m.text.trim());

  return (
    <div className="dv-narrow cx">
      <section className="cx-thread" aria-live="polite">
        {hidden > 0 && (
          <button type="button" className="cx-earlier" onClick={showEarlier}>
            Show earlier ({hidden})
          </button>
        )}

        {items.length === 0 && !sending && (
          <div className="cx-empty">
            <p>Ask the Doctor about this deck. It looks at your list and suggests changes. Nothing changes until you click one.</p>
            <div className="cx-starters">
              {STARTERS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => {
                    onInput(s);
                    boxRef.current?.focus();
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {visible.map((m, i) => {
          const index = hidden + i;
          return (
            <div key={index} className={`cx-turn cx-${m.role}`} ref={index === lastAssistant ? lastReplyRef : undefined}>
              {m.text.trim() &&
                (m.role === "user" ? (
                  <div className="cx-bubble">{m.text}</div>
                ) : (
                  <div className="cx-reply">
                    <ReactMarkdown remarkPlugins={remarkPlugins} components={markdownComponents}>
                      {m.text}
                    </ReactMarkdown>
                  </div>
                ))}
              {m.suggestions.length > 0 && <ChatSuggestions suggestions={m.suggestions} deck={deck} onApply={onApply} />}
            </div>
          );
        })}

        {sending && (
          <div className="cx-thinking" role="status">
            The Doctor is thinking<span aria-hidden>…</span>
          </div>
        )}
      </section>

      <div className="cx-composer">
        {!nearBottom && items.length > 0 && (
          <button type="button" className="cx-jump" onClick={() => scrollToEnd(true)}>
            ↓ Latest
          </button>
        )}
        {notice}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSend();
          }}
        >
          {/* Not disabled while the Doctor answers: a disabled box loses the cursor, and a next question can be typed meanwhile. */}
          <textarea
            ref={boxRef}
            value={input}
            rows={1}
            onChange={(e) => onInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask the Doctor…"
            aria-label="Message to the Doctor"
            maxLength={8000} // The backend refuses a longer message (CHAT_MESSAGE_MAX in api.py).
          />
          <button type="submit" className="btn" disabled={sending || locked || !input.trim()}>
            Send
          </button>
        </form>
        <div className="cx-hint">Enter to send, Shift+Enter for a new line</div>
      </div>
    </div>
  );
}
