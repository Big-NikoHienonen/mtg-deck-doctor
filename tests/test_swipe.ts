/**
 * Tests for the rules of the swipe that changes the card in a card's window (frontend/src/swipe.ts): when a
 * touch becomes a swipe or a scroll, how far the content follows the finger, and when letting go goes to
 * another card. Plain TypeScript with no imports from the page, so Node runs it as it is (Node 22.18 or later;
 * on 22.6 to 22.17 add --experimental-strip-types). Run with
 *
 *     node tests/test_swipe.ts
 */

import { commits, FAR, judge, pull, QUICK, RESIST, START } from "../frontend/src/swipe.ts";

let pass = 0;
let fail = 0;
const check = (name: string, ok: unknown, detail = "") => {
  if (ok) pass++;
  else fail++;
  console.log((ok ? "PASS " : "FAIL ") + name + (detail ? `  [${detail}]` : ""));
};

// --- a touch becomes a swipe, or a scroll, or is still waiting -----------------------------------------

check("a touch that has barely moved is still waiting", judge(3, 4) === "wait" && judge(START - 1, 0) === "wait" && judge(0, -(START - 1)) === "wait");
check("a sideways move is a swipe, left or right", judge(-30, 2) === "swipe" && judge(30, -2) === "swipe");
check("an up or down move is a scroll", judge(2, 40) === "scroll" && judge(-3, -40) === "scroll");
check("a sideways move with a little wobble is still a swipe", judge(60, 30) === "swipe", String(judge(60, 30)));
check("a diagonal move is a scroll", judge(40, 40) === "scroll");
check("a move that is only just up and down enough is a scroll, and just under is a swipe", judge(100, 81) === "scroll" && judge(100, 79) === "swipe");
check("one axis passing the start distance is enough to judge", judge(START, 0) === "swipe" && judge(0, START) === "scroll");

// --- where the content is while the finger moves ---------------------------------------------------------

check("with a card to go to, the content follows the finger exactly", pull(-50, true, true, 375) === -50 && pull(50, true, true, 375) === 50);
check("with no card that way, it gives way only a little", pull(-100, false, true, 375) === -100 * RESIST && pull(100, true, false, 375) === 100 * RESIST);
check("...but a card the other way still moves freely", pull(100, false, true, 375) === 100 && pull(-100, true, false, 375) === -100);
check("it can't be pulled more than 60% of the way across", pull(-900, true, true, 375) === -225 && pull(900, true, true, 375) === 225);
check("it doesn't move when the finger hasn't", pull(0, false, false, 375) === 0);

// --- letting go ------------------------------------------------------------------------------------------

check("a long swipe to the left goes to the next card, to the right to the previous", commits(-FAR, 600, true, true) === "next" && commits(FAR, 600, true, true) === "prev");
check("a swipe a little short of long, and slow, goes nowhere", commits(-(FAR - 1), 600, true, true) === null && commits(FAR - 1, 600, true, true) === null);
check("a short flick goes", commits(-QUICK, 50, true, true) === "next" && commits(QUICK, 50, true, true) === "prev");
check("a short drag that is slow doesn't", commits(-QUICK, 800, true, true) === null);
check("a flick shorter than the minimum doesn't, however fast", commits(-(QUICK - 1), 1, true, true) === null);
check("with no next card, a swipe left goes nowhere; the previous card is still there to the right", commits(-200, 100, false, true) === null && commits(200, 100, false, true) === "prev");
check("with no previous card, a swipe right goes nowhere", commits(200, 100, true, false) === null && commits(-200, 100, true, false) === "next");
check("with no cards at all, nothing goes", commits(-300, 50, false, false) === null && commits(300, 50, false, false) === null);
check("a zero time doesn't divide by zero", commits(-QUICK, 0, true, true) === "next");

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
