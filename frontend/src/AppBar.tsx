import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { signOut, useAuth } from "./authStore";
import Logo from "./Logo";
import NewDeckModal from "./NewDeckModal";
import ThemePicker from "./ThemePicker";
import "./appbar.css";

// The bar along the top of every page: the logo, which goes to the landing page, the places to go from
// anywhere (My decks, My collection, Search cards, Admin), New deck, and the theme. New deck is a
// window over whatever page you are on, so it lives here. Sign out shows when the backend asks for a password.
// Someone who isn't signed in, looking at a deck or at the sign-in page, gets the name and the theme and
// nothing to go to. So does the moment before it is known whether this browser is signed in.
export default function AppBar() {
  const { pathname, search } = useLocation();
  const auth = useAuth();
  const showNav = auth.checked && !auth.unreachable && auth.configured && (!auth.required || auth.signedIn);
  const [newDeckOpen, setNewDeckOpen] = useState(false);

  // My collection and Search cards are both the card search page, told apart by what it was asked.
  const inCollection = pathname === "/search/results" && new URLSearchParams(search).get("collection") === "1";
  const links = [
    { to: "/decks", label: "My decks", current: pathname === "/decks" || pathname.startsWith("/decks/") },
    { to: "/search/results?collection=1", label: "My collection", current: inCollection },
    { to: "/search", label: "Search cards", current: pathname.startsWith("/search") && !inCollection },
    { to: "/admin", label: "Admin", current: pathname === "/admin" },
  ];

  return (
    <header className="app-bar">
      <div className="app-bar-inner">
        {showNav ? (
          <Link to="/" className="app-bar-logo" aria-label="MTG Deck Doctor, home">
            <Logo />
            <span className="app-bar-name">MTG Deck Doctor</span>
          </Link>
        ) : (
          <div className="app-bar-logo">
            <Logo />
            <span className="app-bar-name">MTG Deck Doctor</span>
          </div>
        )}
        {showNav && (
          <>
            <nav className="app-bar-nav" aria-label="Main">
              {links.map((l) => (
                <Link key={l.to} to={l.to} className="app-bar-link" aria-current={l.current ? "page" : undefined}>
                  {l.label}
                </Link>
              ))}
            </nav>
            <button type="button" className="app-bar-new" onClick={() => setNewDeckOpen(true)}>
              New deck
            </button>
            {auth.required && (
              <button type="button" className="app-bar-link" onClick={() => signOut()}>
                Sign out
              </button>
            )}
          </>
        )}
        <ThemePicker />
      </div>
      {newDeckOpen && <NewDeckModal onClose={() => setNewDeckOpen(false)} />}
    </header>
  );
}
