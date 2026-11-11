import { extractText, type Message } from "./api";

// A change the Doctor proposed and the rules accepted. It is only a proposal: the player applies it.
export type Suggestion = { action: "add" | "remove" | "commander"; name: string; why: string };

export type ChatItem = { role: "user" | "assistant"; text: string; suggestions: Suggestion[] };

const ACTIONS = new Set(["add", "remove", "commander"]);

// The accepted proposals in the result of one suggest_changes call. The result is JSON the backend wrote,
// but it is read defensively: a malformed one shows nothing rather than breaking the chat.
function acceptedIn(content: string): Suggestion[] {
  try {
    const accepted: unknown = JSON.parse(content)?.accepted;
    if (!Array.isArray(accepted)) return [];
    return accepted.flatMap((entry) =>
      entry && ACTIONS.has(entry.action) && typeof entry.name === "string" && entry.name
        ? [{ action: entry.action, name: entry.name, why: typeof entry.why === "string" ? entry.why : "" }]
        : [],
    );
  } catch {
    return [];
  }
}

// The conversation as the chat shows it: what was said, and, under the Doctor's last words of each turn,
// the changes it proposed during that turn. A proposal made twice in a turn shows once.
export function chatItems(messages: Message[]): ChatItem[] {
  const results = new Map<string, string>();
  for (const m of messages) {
    if (typeof m.content === "string") continue;
    for (const block of m.content) if (block.type === "tool_result") results.set(block.tool_use_id, block.content);
  }

  const items: ChatItem[] = [];
  let pending = new Map<string, Suggestion>();
  let lastReply: ChatItem | null = null;

  const endTurn = () => {
    if (pending.size > 0) {
      const suggestions = [...pending.values()];
      if (lastReply) lastReply.suggestions = suggestions;
      else items.push({ role: "assistant", text: "", suggestions });
    }
    pending = new Map();
    lastReply = null;
  };

  for (const m of messages) {
    const text = extractText(m.content);
    if (m.role === "user") {
      // A user message that only carries tool results is part of the turn, not the start of one.
      if (text.trim()) {
        endTurn();
        items.push({ role: "user", text, suggestions: [] });
      }
      continue;
    }
    if (typeof m.content !== "string") {
      for (const block of m.content) {
        if (block.type !== "tool_use" || block.name !== "suggest_changes") continue;
        for (const s of acceptedIn(results.get(block.id) ?? "")) pending.set(`${s.action}:${s.name}`, s);
      }
    }
    if (text.trim()) {
      lastReply = { role: "assistant", text, suggestions: [] };
      items.push(lastReply);
    }
  }
  endTurn();
  return items;
}
