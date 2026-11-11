import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import Logo from "./Logo";
import NewDeckModal from "./NewDeckModal";
import ThemePicker from "./ThemePicker";
import "./appbar.css";

// The bar along the top of every page: the logo, which goes home, the places to go from anywhere,
// New deck, and the theme. New deck is a window over whatever page you are on, so it lives here.
export default function AppBar() {
  const { pathname, search } = useLocation();
  const [newDeckOpen, setNewDeckOpen] = useState(false);

  // My collection and Search cards are both the card search page, told apart by what it was asked.
  const inCollection = pathname === "/search/results" && new URLSearchParams(search).get("collection") === "1";
  const links = [
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
        <ThemePicker />
      </div>
      {newDeckOpen && <NewDeckModal onClose={() => setNewDeckOpen(false)} />}
    </header>
  );
}
