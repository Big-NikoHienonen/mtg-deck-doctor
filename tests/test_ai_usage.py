"""Tests for the limits on the Doctor's model use: the usage log and its cost estimate, the
daily budget, what the chat is shown of earlier turns, the cap on tool calls per message, and
the endpoints that report them. The model is stubbed, so no network and no cost. Run with

    uv run python tests/test_ai_usage.py
"""

import copy
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from fastapi.testclient import TestClient

import mtg_deck_doctor.deck as D
import mtg_deck_doctor.tool_loop as T
import mtg_deck_doctor.usage as U
from mtg_deck_doctor import api
from mtg_deck_doctor.deck import Deck

tmp = Path(tempfile.mkdtemp())
D.DECKS_DIR = tmp / "decks"
results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def fresh_usage_log() -> None:
    U.USAGE_PATH = tmp / f"usage-{len(results)}.jsonl"
    U._today.update(day=None, usd=0.0)


def usage_block(input=0, output=0, cache_read=0, cache_write=0):
    return SimpleNamespace(input_tokens=input, output_tokens=output, cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write)


# --- settings: a blank value, as a copied .env.example leaves, counts as unset ---------------------------------
os.environ["SETTING_A"], os.environ["SETTING_B"], os.environ["SETTING_C"] = "", "   ", " haiku "
os.environ.pop("SETTING_D", None)
check("a setting that is blank, spaces, or missing falls back to its default; a real one is used", [T.env_setting(n, "d") for n in ("SETTING_A", "SETTING_B", "SETTING_C", "SETTING_D")] == ["d", "d", "haiku", "d"])
check("the defaults in force are the intended ones", T.MODEL and T.CHAT_EFFORT in ("low", "medium", "high", "xhigh", "max") and T.MAX_TOOL_ROUNDS >= 2)
rounds = []
for value in (None, "", "lots", "1", "7"):
    os.environ.pop("CHAT_MAX_TOOL_ROUNDS", None) if value is None else os.environ.__setitem__("CHAT_MAX_TOOL_ROUNDS", value)
    rounds.append(T._rounds_setting())
os.environ.pop("CHAT_MAX_TOOL_ROUNDS", None)
check("the cap on a message's model calls is 20 unless set, never below 2, and ignores what isn't a number", rounds == [20, 20, 20, 2, 7], str(rounds))

# --- the cost estimate ---------------------------------------------------------------------------
u = usage_block(input=1000, output=500, cache_read=2000, cache_write=400)
check("cost: fresh input, output, cache reads at a tenth and cache writes at 1.25x, per million tokens", abs(U.cost_usd("claude-sonnet-5", u) - (1000 * 2 + 2000 * 2 * 0.1 + 400 * 2 * 1.25 + 500 * 10) / 1e6) < 1e-12, str(U.cost_usd("claude-sonnet-5", u)))
check("...Haiku is a twentieth of Sonnet's price", abs(U.cost_usd("claude-sonnet-5-5", u) / U.cost_usd("claude-haiku-5-5", u) - 20) < 1e-9)
check("...a model that isn't listed is charged at Sonnet's rate", U.cost_usd("some-future-model", u) == U.cost_usd("claude-sonnet-5", u))

# --- the log and the day's total -------------------------------------------------------------------
fresh_usage_log()
os.environ["AI_DAILY_BUDGET_USD"] = "0.02"
first = U.record("chat", "claude-sonnet-5", usage_block(input=1000, output=500), "end_turn", 1.234)
lines = [json.loads(line) for line in U.USAGE_PATH.read_text().splitlines()]
check("a call is logged as one line: feature, model, tokens, cost, stop reason, seconds", len(lines) == 1 and lines[0]["feature"] == "chat" and lines[0]["input"] == 1000 and lines[0]["output"] == 500 and lines[0]["stop"] == "end_turn" and lines[0]["seconds"] == 1.23 and abs(lines[0]["usd"] - first) < 1e-6, str(lines))
check("...and added to today's total", abs(U.spent_today() - first) < 1e-9)
U._today.update(day=None, usd=0.0)
check("...which is rebuilt from the file after a restart", abs(U.spent_today() - first) < 1e-9)
yesterday = (U._now().replace(hour=12) - __import__("datetime").timedelta(days=1)).isoformat(timespec="seconds")
with U.USAGE_PATH.open("a") as f:
    f.write(json.dumps({"at": yesterday, "feature": "chat", "usd": 99.0}) + "\n")
    f.write("{half a line\n")
U._today.update(day=None, usd=0.0)
check("...counting only today's calls, and skipping a line that isn't JSON", abs(U.spent_today() - first) < 1e-9, str(U.spent_today()))

# --- the budget ------------------------------------------------------------------------------------
fresh_usage_log()
os.environ["AI_DAILY_BUDGET_USD"] = "0.02"
U.check_budget()
U.record("chat", "claude-sonnet-5", usage_block(input=1000, output=500))      # about a cent
U.check_budget()
U.record("chat", "claude-sonnet-5", usage_block(input=1000, output=500))
U.record("chat", "claude-sonnet-5", usage_block(input=1000, output=500))
try:
    U.check_budget(); err = None
except U.AiBudgetExceeded as e:
    err = e
check("once the day's estimated cost reaches the limit, the next call is refused", err is not None and err.spent >= err.limit == 0.02 and 0 < err.resets_in <= 86400, str(err))
for value in (None, "", "  ", "0", "-3", "lots"):
    os.environ.pop("AI_DAILY_BUDGET_USD", None) if value is None else os.environ.__setitem__("AI_DAILY_BUDGET_USD", value)
    U.check_budget()   # however much has been spent, none of these refuses a call
check("with no limit set, or a blank, zero, negative or unreadable one, nothing is ever refused", U.daily_budget() == U.DEFAULT_DAILY_BUDGET_USD == 0.0 and U.spent_today() > 0)
os.environ["AI_DAILY_BUDGET_USD"] = "0.02"
status, body = api.ai_errors.describe_budget(0.05, 0.02, 7200)
check("the refusal is a 429 that only a person can clear, saying when it resets", status == 429 and body["code"] == "ai_budget" and body["retry_after"] is None and "2 hours" in body["detail"] and "AI_DAILY_BUDGET_USD" in body["detail"], str(body))

fresh_usage_log()
U.record("chat", "claude-sonnet-5", usage_block(input=2000, output=300, cache_read=1000))
U.record("chat", "claude-sonnet-5", usage_block(input=500, output=100))
U.record("structured:plan", "claude-sonnet-5", usage_block(input=100, output=50))
summary = U.summary(7)
check("the summary groups usage by day and by feature, dearest first", list(summary["by_feature"]) == ["chat", "structured:plan"] and summary["by_feature"]["chat"]["calls"] == 2 and summary["by_feature"]["chat"]["input"] == 2500 and summary["by_feature"]["chat"]["cache_read"] == 1000 and sum(d["calls"] for d in summary["by_day"].values()) == 3, str(summary))
check("...with today's totals, tokens included", summary["today"]["calls"] == 3 and summary["today"]["input"] == 2600 and summary["today"]["output"] == 450 and summary["today"]["cache_read"] == 1000 and abs(summary["today"]["usd"] - summary["today_usd"]) < 1e-3, str(summary["today"]))
check("...and the newest calls first, as many as asked for", [e["feature"] for e in summary["recent"]] == ["structured:plan", "chat", "chat"] and [e["feature"] for e in U.summary(7, 1)["recent"]] == ["structured:plan"] and U.summary(7, 0)["recent"] == [], str([e["feature"] for e in summary["recent"]]))
os.environ.pop("AI_DAILY_BUDGET_USD", None)
unset = U.summary(7)["daily_budget_usd"]
os.environ["AI_DAILY_BUDGET_USD"] = "0.02"
check("...showing the daily limit only when one is set", unset is None and U.summary(7)["daily_budget_usd"] == 0.02)

# --- what the chat is shown of earlier turns -----------------------------------------------------------
def user(text): return {"role": "user", "content": text}
def asst(*blocks): return {"role": "assistant", "content": list(blocks)}
def think(n=1): return {"type": "thinking", "thinking": "hmm " * 50 * n, "signature": "sig"}
def txt(t): return {"type": "text", "text": t}
def call(i, tool="lookup_card", **inp): return {"type": "tool_use", "id": i, "name": tool, "input": inp or {"name": "X"}}
def result(i, body="{}"): return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": body}]}

history = [
    user("build me a deck"),
    asst(think(), txt("Looking."), call("a1", "search_cards", q="x")),
    result("a1", "BIG SEARCH RESULT"),
    asst(think(), call("a2", "lookup_card", name="Sol Ring")),
    result("a2", "SOL RING TEXT"),
    asst(think(), txt("Added Sol Ring.")),
    user("what about a rock?"),
    asst(think(), txt("Try Arcane Signet.")),
    user("tell me about Sol Ring"),                    # the current turn
    asst(think(), call("c1", "lookup_card", name="Sol Ring")),
    result("c1", "SOL RING AGAIN"),
]
before = copy.deepcopy(history)
shown = T.compact_history(history)
check("compaction leaves the stored conversation as it was", history == before)
check("the current turn is sent whole, thinking included", shown[-3:] == history[-3:] and any(b["type"] == "thinking" for b in shown[-2]["content"]))
check("earlier turns lose their thinking and the tool calls that aren't lookups", not any(b.get("type") == "thinking" for m in shown[:-3] for b in (m["content"] if isinstance(m["content"], list) else [])) and "BIG SEARCH RESULT" not in json.dumps(shown) and "search_cards" not in json.dumps(shown))
check("...but keep what was said, and the card text from a lookup", "Looking." in json.dumps(shown) and "Added Sol Ring." in json.dumps(shown) and "SOL RING TEXT" in json.dumps(shown) and shown[0] == history[0])

def pairs_valid(messages):
    """Every tool call is answered in the very next message, and every result answers a call just before it."""
    for i, m in enumerate(messages):
        if not isinstance(m["content"], list): continue
        ids = [b["id"] for b in m["content"] if b.get("type") == "tool_use"]
        answers = [b["tool_use_id"] for b in (messages[i + 1]["content"] if i + 1 < len(messages) and isinstance(messages[i + 1]["content"], list) else []) if b.get("type") == "tool_result"]
        if ids and sorted(ids) != sorted(answers): return False
        if m["role"] == "user" and any(b.get("type") == "tool_result" for b in m["content"]):
            prev = messages[i - 1]["content"] if i else []
            if not (isinstance(prev, list) and {b["tool_use_id"] for b in m["content"] if b.get("type") == "tool_result"} <= {b["id"] for b in prev if b.get("type") == "tool_use"}): return False
    return True

check("what is shown is a valid conversation: it starts with the user and every tool call has its result", shown[0]["role"] == "user" and pairs_valid(shown))
check("a conversation that is only the current turn is sent as it is", T.compact_history(history[-3:]) == history[-3:])

many = [user("start")]
for i in range(30):
    many += [asst(call(f"l{i}", "lookup_card", name=f"Card {i}")), result(f"l{i}", f"TEXT {i}"), asst(txt(f"done {i}")), user(f"next {i}")]
many += [asst(txt("final"))]
shown = T.compact_history(many)
turn_starts = [m for m in shown if m["role"] == "user" and isinstance(m["content"], str)]
kept_lookups = [b["id"] for m in shown if isinstance(m["content"], list) for b in m["content"] if b.get("type") == "tool_use"]
check("at most 20 turns are shown, the latest ones", len(turn_starts) == T.HISTORY_TURNS and turn_starts[-1]["content"] == "next 29" and turn_starts[0]["content"] == "next 10", str([m["content"] for m in turn_starts][:2]))
check("...and of the lookups in earlier turns, the 12 most recent are kept", kept_lookups == [f"l{i}" for i in range(18, 30)], str(kept_lookups))
check("...still a valid conversation", pairs_valid(shown) and shown[0]["role"] == "user")
check("a long history is a fraction of its full size", len(json.dumps(shown)) < len(json.dumps(many)) * 0.6, f"{len(json.dumps(shown))} vs {len(json.dumps(many))}")
note = T._with_wrap_up_note([user("hi"), asst(call("z")), result("z")])
check("the wrap-up note goes on the last message and nowhere else", note[-1]["content"][-1] == {"type": "text", "text": T.WRAP_UP_NOTE} and len(note[-1]["content"]) == 2 and note[:-1] == [user("hi"), asst(call("z"))])
check("...also when that message is plain text", T._with_wrap_up_note([user("hi")])[-1]["content"] == [{"type": "text", "text": "hi"}, {"type": "text", "text": T.WRAP_UP_NOTE}])

# --- the chat loop, with a stub for the model -----------------------------------------------------------
def response(blocks, stop="end_turn", **kw):
    return SimpleNamespace(content=blocks, stop_reason=stop, usage=usage_block(**{"input": 100, "output": 20, **kw}))
def block_text(t): return SimpleNamespace(type="text", text=t)
def block_call(i, tool="lookup_card", **inp): return SimpleNamespace(type="tool_use", id=i, name=tool, input=inp or {"name": "Sol Ring"})

requests: list[dict] = []
script: list = []
class StubMessages:
    def create(self, **kwargs):
        requests.append(kwargs)
        return script.pop(0)(kwargs) if callable(script[0]) else script.pop(0)
T.client = SimpleNamespace(messages=StubMessages())
T.make_tool_implementations = lambda deck: {"lookup_card": lambda name: {"name": name, "oracle_text": "text"}}
T.refresh_if_stale = lambda deck: None
os.environ["AI_DAILY_BUDGET_USD"] = "0"   # the stub's usage shouldn't trip the limit in these

deck = Deck(id="t1", commander="Atarka, World Render", cards=["Sol Ring"])

def propose_widgets():
    return T._run_structured_loop("system", "user", [], "return_widgets", "widgets")

fresh_usage_log(); requests.clear()
script[:] = [response([SimpleNamespace(type="tool_use", id="f1", name="return_widgets", input={"widgets": [1]})], "tool_use")]
propose_widgets()
check("a structured call is logged under the name of the function that made it", [json.loads(line)["feature"] for line in U.USAGE_PATH.read_text().splitlines()] == ["structured:propose_widgets"])

fresh_usage_log(); requests.clear(); script[:] = [response([block_text("Hello.")])]
reply, msgs = T.run_conversation(deck, [], "hi")
req = requests[0]
check("a plain reply is one call, saved as the user's message and the Doctor's", reply == "Hello." and len(requests) == 1 and [m["role"] for m in msgs] == ["user", "assistant"])
check("...with the instructions in a cached block and the deck's state after it, in its own block", isinstance(req["system"], list) and req["system"][0]["cache_control"] == {"type": "ephemeral"} and "Current deck state" not in req["system"][0]["text"] and req["system"][1]["text"].startswith("Current deck state") and "Sol Ring" in req["system"][1]["text"] and "cache_control" not in req["system"][1], str([b.get("cache_control") for b in req["system"]]))
check("...the conversation so far cached too, effort set, and no limit on tools yet", req["cache_control"] == {"type": "ephemeral"} and req["output_config"] == {"effort": T.CHAT_EFFORT} and "tool_choice" not in req and req["model"] == T.MODEL)
logged = [json.loads(line) for line in U.USAGE_PATH.read_text().splitlines()]
check("...and the call is in the usage log as chat", [e["feature"] for e in logged] == ["chat"] and logged[0]["input"] == 100)

fresh_usage_log(); requests.clear()
script[:] = [response([block_call("t1")], "tool_use"), response([block_call("t2")], "tool_use"), response([block_text("Done.")])]
reply, msgs = T.run_conversation(deck, [], "look up a card")
check("a turn with tool calls goes round until the model stops", reply == "Done." and len(requests) == 3 and [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user", "assistant"] and pairs_valid(msgs))

# a model that never stops calling tools
fresh_usage_log(); requests.clear()
script[:] = [response([block_call(f"r{i}")], "tool_use") for i in range(T.MAX_TOOL_ROUNDS - 1)] + [response([block_text("I looked at a lot of cards; ask me to continue.")])]
reply, msgs = T.run_conversation(deck, [], "look up everything")
last = requests[-1]
check("a turn is cut off at the cap: the last call has no tools to use and the instruction to wrap up", len(requests) == T.MAX_TOOL_ROUNDS and last["tool_choice"] == {"type": "none"} and last["messages"][-1]["content"][-1]["text"] == T.WRAP_UP_NOTE and all("tool_choice" not in r for r in requests[:-1]), str(len(requests)))
check("...and it ends in a reply, with a conversation that can be continued", reply.startswith("I looked at a lot") and msgs[-1]["role"] == "assistant" and pairs_valid(msgs))
check("...the instruction is for that call only, never saved", T.WRAP_UP_NOTE not in json.dumps(msgs))

# one that ignores the instruction
fresh_usage_log(); requests.clear()
script[:] = [response([block_call(f"s{i}")], "tool_use") for i in range(T.MAX_TOOL_ROUNDS - 1)] + [response([block_call("last")], "tool_use")]
reply, msgs = T.run_conversation(deck, [], "look up everything")
check("a model that calls a tool anyway on the last call gets no more: no call is saved without a result, and there is still a reply", len(requests) == T.MAX_TOOL_ROUNDS and not any(b["type"] == "tool_use" for b in msgs[-1]["content"]) and "continue" in reply and pairs_valid(msgs))

# earlier turns are compacted in what is sent
fresh_usage_log(); requests.clear(); script[:] = [response([block_text("Sure.")])]
T.run_conversation(deck, history[:8], "and another?")
sent = json.dumps(requests[0]["messages"])
check("what the chat sends has earlier turns compacted, while the stored conversation keeps everything", "BIG SEARCH RESULT" not in sent and "hmm hmm" not in sent and "SOL RING TEXT" in sent and sent.count('"type": "thinking"') == 0)

# the budget stops a turn before it reaches the model
fresh_usage_log(); requests.clear()
os.environ["AI_DAILY_BUDGET_USD"] = "0.001"
U.record("chat", "claude-sonnet-5", usage_block(input=100000))
try:
    T.run_conversation(deck, [], "hi"); stopped = False
except U.AiBudgetExceeded:
    stopped = True
check("with the day's budget spent, a chat message is refused before any call", stopped and requests == [])

# --- over HTTP -----------------------------------------------------------------------------------------
c = TestClient(api.app, raise_server_exceptions=False)
made = c.post("/decks").json()
r = c.post(f"/decks/{made['id']}/chat", json={"message": "hi"})
check("chat over budget -> 429 with the code the page treats as needing a person, and nothing sent to the model", r.status_code == 429 and r.json()["code"] == "ai_budget" and r.json()["retry_after"] is None and requests == [], r.text[:200])
r = c.get("/ai/status")
check("the status check says so too, so \"check again\" can't hide it", r.status_code == 429 and r.json()["code"] == "ai_budget" and requests == [])
os.environ["AI_DAILY_BUDGET_USD"] = "50"
r = c.get("/usage?days=7")
body = r.json()
check("/usage reports today's totals, the limit, the split by feature and the newest calls", r.status_code == 200 and body["daily_budget_usd"] == 50 and "chat" in body["by_feature"] and body["today_usd"] > 0 and body["today"]["calls"] > 0 and len(body["recent"]) > 0, str(body)[:200])
check("...with the settings that shape spending", body["settings"] == {"model": T.MODEL, "chat_effort": T.CHAT_EFFORT, "max_tool_rounds": T.MAX_TOOL_ROUNDS}, str(body["settings"]))
check("...and keeps the number of days and calls sensible", c.get("/usage?days=0").status_code == 200 and c.get("/usage?days=100000").status_code == 200 and len(c.get("/usage?recent=1").json()["recent"]) == 1 and c.get("/usage?recent=-5").json()["recent"] == [])

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
