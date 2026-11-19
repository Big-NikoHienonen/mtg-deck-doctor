import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Deck } from "./api";
import ChatSuggestions from "./ChatSuggestions";
import type { ChatItem, Suggestion } from "./chatMessages";
import "./correspondence.css";

// How much of the conversation is shown when the panel opens, and how much more each "Show earlier" brings.
// What people come back for is the last exchange; the rest is one click away.
const FIRST_SHOWN = 6;
const SHOWN_MORE = 20;

// The distance from the end of the conversation, in pixels, within which it counts as "at the end": close
// enough that a new reply should scroll into view rather than wait behind a button.
const NEAR_END = 120;

const STARTERS = ["What should I cut from this deck?", "Where is my mana base weakest?", "Suggest some card draw that fits my commander"];

const remarkPlugins = [remarkGfm];

// A table is wider than the panel, so it scrolls sideways inside its own box instead of stretching the panel.
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
  onClose: () => void;
};

// The conversation with the Doctor, in a panel over the right side of the deck page. The deck stays in view
// beside it, and a change the Doctor proposes shows in the deck as soon as it is applied. The conversation
// scrolls inside the panel, so the page behind never moves; a click outside the panel, or Escape, closes it.
export default function Correspondence({ deck, items, sending, input, onInput, onSend, locked, notice, onApply, onClose }: Props) {
  const [shown, setShown] = useState(FIRST_SHOWN);
  const [nearEnd, setNearEnd] = useState(true);
  const nearEndRef = useRef(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const lastReplyRef = useRef<HTMLDivElement>(null);
  const seenCount = useRef(items.length);
  const heightBeforeEarlier = useRef<number | null>(null);

  const hidden = Math.max(0, items.length - shown);
  const visible = items.slice(hidden);
  const lastRole = items.at(-1)?.role;

  const scrollToEnd = useCallback((smooth: boolean) => {
    const area = scrollRef.current;
    area?.scrollTo({ top: area.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, []);

  // Opens on the latest message, or at the first line of it when the Doctor's last answer is longer than the
  // panel, as it would for an answer that came in while the panel was open. On a computer the cursor goes to
  // the box too; on a phone it would only bring the keyboard up over the conversation.
  useLayoutEffect(() => {
    const area = scrollRef.current;
    const reply = lastReplyRef.current;
    if (area && reply && lastRole === "assistant" && reply.offsetHeight > area.clientHeight) {
      area.scrollTop += reply.getBoundingClientRect().top - area.getBoundingClientRect().top;
    } else {
      scrollToEnd(false);
    }
    handleScroll(); // Whether it opened away from the end, for the "Latest" button.
    if (window.matchMedia("(pointer: fine)").matches) boxRef.current?.focus({ preventScroll: true });
    // Only when the panel opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The page behind stays where it is while the panel is open. The scrollbar's width is kept as padding, so
  // the deck doesn't shift sideways when the scrollbar goes.
  useEffect(() => {
    const { overflow, paddingRight } = document.body.style;
    const scrollbar = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = "hidden";
    if (scrollbar > 0) document.body.style.paddingRight = `${scrollbar}px`;
    return () => {
      document.body.style.overflow = overflow;
      document.body.style.paddingRight = paddingRight;
    };
  }, []);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape" && !e.isComposing) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function handleScroll() {
    const area = scrollRef.current;
    if (!area) return;
    const near = area.scrollHeight - area.scrollTop - area.clientHeight < NEAR_END;
    nearEndRef.current = near;
    setNearEnd(near);
  }

  // Your own message goes to the end. The Doctor's reply scrolls to where the reply begins, so a long answer
  // is read from its first line, unless you had scrolled up to read something, in which case the button says
  // there is more below.
  useEffect(() => {
    if (items.length === seenCount.current) return;
    const grew = items.length > seenCount.current;
    seenCount.current = items.length;
    if (!grew) return;
    if (lastRole === "user") scrollToEnd(true);
    else if (nearEndRef.current) lastReplyRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [items.length, lastRole, scrollToEnd]);

  // Older messages are added above what is on screen, so the panel is moved by the height they add, and the
  // message being read stays where it was.
  useLayoutEffect(() => {
    const area = scrollRef.current;
    if (heightBeforeEarlier.current === null || !area) return;
    area.scrollTop += area.scrollHeight - heightBeforeEarlier.current;
    heightBeforeEarlier.current = null;
  }, [shown]);

  const showEarlier = () => {
    heightBeforeEarlier.current = scrollRef.current?.scrollHeight ?? null;
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
    <>
      <div className="cx-scrim" onClick={onClose} aria-hidden />
      <aside className="cx" role="dialog" aria-modal="true" aria-label="Correspondence with the Doctor">
        <header className="cx-head">
          <h2>Correspondence</h2>
          <button type="button" className="cx-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </header>

        <div className="cx-scroll" ref={scrollRef} onScroll={handleScroll}>
          <section className="cx-thread" role="log" aria-label="Conversation">
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
        </div>

        <div className="cx-composer">
          {!nearEnd && items.length > 0 && (
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
          <div className="cx-hint">Enter to send, Shift+Enter for a new line, Esc to close</div>
        </div>
      </aside>
    </>
  );
}
