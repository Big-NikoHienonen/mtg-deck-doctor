"""Tests for the Doctor's chat: a turn cut off in the middle of a tool call is never saved. No
network and no model: both are stubbed. Run with

    uv run python tests/test_chat.py
"""

import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient

import mtg_deck_doctor.deck as D
import mtg_deck_doctor.tool_loop as T
from mtg_deck_doctor import api

D.DECKS_DIR = Path(tempfile.mkdtemp()) / "decks"
results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


T.refresh_if_stale = lambda deck: None
c = TestClient(api.app, raise_server_exceptions=False)

# --- a turn cut off in the middle of a tool call is never saved ---------------------------

cut_off = [{"role": "user", "content": "q"}, {"role": "assistant", "content": [{"type": "text", "text": "Looking."}, {"type": "tool_use", "id": "t1", "name": "lookup_card", "input": {}}]}]
finished = [{"role": "user", "content": "q"}, {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}]
check("a last turn whose tool calls never got results is dropped from a saved history; a finished one stays", T._without_dangling_tool_use(cut_off) == cut_off[:1] and T._without_dangling_tool_use(finished) == finished and T._without_dangling_tool_use([]) == [])
sent: list = []
answer = {"stop": "max_tokens", "content": [NS(type="tool_use", id="t2", name="lookup_card", input={})]}
T.client = NS(messages=NS(create=lambda **kw: (sent.append(kw["messages"]), NS(stop_reason=answer["stop"], content=answer["content"]))[1]))
try:
    T.run_conversation(D.Deck(id="chat1"), finished, "next")
    raised = False
except T.ConversationCutOff:
    raised = True
check("a reply cut off at the token limit in the middle of a tool call raises instead of being returned", raised)
answer.update(stop="end_turn", content=[NS(type="text", text="Here you go.")])
text, saved = T.run_conversation(D.Deck(id="chat2"), cut_off, "next")
check("a history left with a dangling tool call is repaired before it is sent, and the chat goes on", text == "Here you go." and all(m["role"] != "assistant" or not any(b.get("type") == "tool_use" for b in m["content"]) for m in sent[-1]), str([m["role"] for m in sent[-1]]))
check("...and the chat endpoint answers a cut-off turn with a 502 and a reason, saving nothing", (lambda r: r.status_code == 502 and "ran out of room" in r.json()["detail"])((answer.update(stop="max_tokens", content=[NS(type="tool_use", id="t3", name="lookup_card", input={})]), D.save_deck(D.Deck(id="chat3")), c.post("/decks/chat3/chat", json={"message": "hi"}))[2]))

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
