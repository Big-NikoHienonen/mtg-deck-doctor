import { Outlet } from "react-router-dom";
import { BackendDown, Card, Note } from "./AuthCards";
import { useAuth } from "./authStore";
import SignInForm from "./SignInForm";

// Stands in front of the owner's pages: the page shows once this browser is signed in, and the sign-in
// form shows until then. When the backend doesn't ask for a password, the page shows at once. A deck's
// own page isn't behind this: anyone can look at a deck (see DeckRoute.tsx).
export default function AuthGate() {
  const auth = useAuth();

  if (!auth.checked) return null;
  if (auth.unreachable) return <BackendDown />;
  if (!auth.configured) {
    return (
      <Card title="No password is set">
        <Note>
          The backend won't open to anyone without one. Set <code>MTG_DECK_DOCTOR_PASSWORD</code> in its environment and restart it.
        </Note>
      </Card>
    );
  }
  if (auth.required && !auth.signedIn) {
    return (
      <Card title="Sign in">
        <SignInForm />
      </Card>
    );
  }
  return <Outlet />;
}
