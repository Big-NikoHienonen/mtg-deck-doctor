import { BackendDown } from "./AuthCards";
import { useAuth } from "./authStore";
import DeckView from "./DeckView";
import PublicDeckView from "./PublicDeckView";

// A deck's address. Anyone can open it: signed in, it is the whole deck page, with everything that
// edits the deck and the Doctor; otherwise it is the list to look at. Signing in, or the session
// ending, swaps one for the other without leaving the address.
export default function DeckRoute() {
  const auth = useAuth();

  if (!auth.checked) return null;
  if (auth.unreachable) return <BackendDown />;
  return !auth.required || auth.signedIn ? <DeckView /> : <PublicDeckView />;
}
