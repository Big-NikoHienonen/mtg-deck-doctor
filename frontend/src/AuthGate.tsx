import { Outlet } from "react-router-dom";
import { BackendDown } from "./AuthCards";
import { useAuth } from "./authStore";
import GuestLanding from "./GuestLanding";

// Stands in front of the owner's pages: the page shows once this browser is signed in, and until then
// a visitor gets the front door (GuestLanding) at every one of these addresses. When the backend doesn't
// ask for a password, the page shows at once. A deck's own page isn't behind this: anyone with its
// address can look at it (see DeckRoute.tsx).
export default function AuthGate() {
  const auth = useAuth();

  if (!auth.checked) return null;
  if (auth.unreachable) return <BackendDown />;
  if (auth.required && !auth.signedIn) return <GuestLanding />;
  return <Outlet />;
}
