import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { signOut, useAuth } from "./authStore";
import Logo from "./Logo";
import NewDeckModal from "./NewDeckModal";
import ThemePicker from "./ThemePicker";
import "./appbar.css";

// The bar along the top of every page: the logo, which goes to the landing page, the places to go from
// anywhere (My decks, Browse, My collection, Search cards, Admin), New deck, and the theme. New deck is a
// window over whatever page you are on, so it lives here. Your username, which opens your profile, and
// Sign out show when the backend asks for a sign-in.
// Someone who isn't signed in gets the name, Browse (which needs no sign-in), a Sign in link (to the
// sign-in page, which brings them back here) and the theme, and nothing else to go to. So does the moment
// before it is known whether this browser is signed in.
export default function AppBar() {
  const { pathname, search } = useLocation();
  const auth = useAuth();
  const loaded = auth.checked && !auth.unreachable;
  const showNav = loaded && (!auth.required || auth.signedIn);
  const visitor = loaded && auth.required && !auth.signedIn;
  const [newDeckOpen, setNewDeckOpen] = useState(false);
  // On a phone the links are a list under a Menu button, not a row; on a computer this is never used.
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  // My collection and Search cards are both the card search page, told apart by what it was asked.
  const inCollection = pathname === "/search/results" && new URLSearchParams(search).get("collection") === "1";
  const links = [
    { to: "/decks", label: "My decks", current: pathname === "/decks" || pathname.startsWith("/decks/") },
    { to: "/browse", label: "Browse", current: pathname === "/browse" },
    { to: "/search/results?collection=1", label: "My collection", current: inCollection },
    { to: "/search", label: "Search cards", current: pathname.startsWith("/search") && !inCollection },
    { to: "/admin", label: "Admin", current: pathname === "/admin" },
  ];

  return (
    <header className="app-bar">
      <div className="app-bar-inner">
        <Link to="/" className="app-bar-logo" aria-label="MTG Deck Doctor, home">
          <Logo />
          <span className="app-bar-name">MTG Deck Doctor</span>
        </Link>
        {showNav && (
          <>
            {/* The links and the account. Choosing one closes the menu on a phone. */}
            <div id="app-bar-links" className={`app-bar-links${menuOpen ? " is-open" : ""}`} onClick={(e) => (e.target as HTMLElement).closest("a, button") && setMenuOpen(false)}>
              <nav className="app-bar-nav" aria-label="Main">
                {links.map((l) => (
                  <Link key={l.to} to={l.to} className="app-bar-link" aria-current={l.current ? "page" : undefined}>
                    {l.label}
                  </Link>
                ))}
              </nav>
              {auth.required && (
                <div className="app-bar-account">
                  <Link to="/profile" className="app-bar-link" aria-current={pathname === "/profile" ? "page" : undefined} title={auth.email ? `Signed in as ${auth.email}` : undefined}>
                    {auth.username ?? "Set username"}
                  </Link>
                  <button type="button" className="app-bar-link" onClick={() => signOut()}>
                    Sign out
                  </button>
                </div>
              )}
            </div>
            <button type="button" className="app-bar-new" onClick={() => setNewDeckOpen(true)}>
              New deck
            </button>
            <button type="button" className="app-bar-menu" aria-label="Menu" aria-expanded={menuOpen} aria-controls="app-bar-links" onClick={() => setMenuOpen((open) => !open)}>
              <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
                <path d="M3 5.5h14M3 10h14M3 14.5h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
              </svg>
            </button>
            {menuOpen && <div className="app-bar-scrim" onClick={() => setMenuOpen(false)} aria-hidden />}
          </>
        )}
        {visitor && (
          <Link to="/browse" className="app-bar-link" aria-current={pathname === "/browse" ? "page" : undefined}>
            Browse
          </Link>
        )}
        {visitor && pathname !== "/login" && (
          <Link to="/login" state={{ from: pathname + search }} className="app-bar-link">
            Sign in
          </Link>
        )}
        <ThemePicker />
      </div>
      {newDeckOpen && <NewDeckModal onClose={() => setNewDeckOpen(false)} />}
    </header>
  );
}
