import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getDeck } from "./api";
import { BackendDown } from "./AuthCards";
import { useAuth } from "./authStore";
import DeckView from "./DeckView";
import PublicDeckView from "./PublicDeckView";

// A deck's address. Its owner gets the whole deck page, with everything that edits the deck and the Doctor.
// Everyone else, signed in or not, gets the list to look at, if the deck is public, and "no deck at this
// address" if it is private or isn't there. Signing in, or the session ending, swaps one for the other
// without leaving the address.
export default function DeckRoute() {
  const auth = useAuth();
  const { deckId } = useParams<{ deckId: string }>();
  // Whose deck this is, once it has been asked: the id it was asked about, and whether the signed-in user
  // owns it. An answer about another deck doesn't count.
  const [answer, setAnswer] = useState<{ deckId: string; mine: boolean } | null>(null);
  const signedIn = auth.required && auth.signedIn;
  const mine = answer !== null && answer.deckId === deckId ? answer.mine : null;

  useEffect(() => {
    if (!signedIn || !deckId) return;
    let stale = false;
    // The owner's route answers for the owner's decks only, so an answer tells whose deck this is. If it
    // can't be asked, the owner's page is shown, since it explains what went wrong.
    getDeck(deckId)
      .then((deck) => !stale && setAnswer({ deckId, mine: deck !== null }))
      .catch(() => !stale && setAnswer({ deckId, mine: true }));
    return () => {
      stale = true;
    };
  }, [signedIn, deckId]);

  if (!auth.checked) return null;
  if (auth.unreachable) return <BackendDown />;
  if (!auth.required) return <DeckView />;
  if (!signedIn) return <PublicDeckView />;
  if (mine === null) return null;
  return mine ? <DeckView /> : <PublicDeckView />;
}
