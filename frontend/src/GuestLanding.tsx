import Logo from "./Logo";
import "./guest.css";

const FEATURES = [
  {
    title: "AI-powered",
    text: "The Doctor reviews your list, finds what's missing and what to cut, and answers your questions. It only suggests: nothing changes until you click.",
  },
  {
    title: "Great card search",
    text: "Search every Magic card with Scryfall's full syntax, and see what's new from the latest sets.",
  },
  {
    title: "A top-tier deck builder",
    text: "Group, sort and price your list, pick printings, track what you own, and open any card for its details and rulings.",
  },
];

// The front door for someone who isn't signed in: the mark, what the app is, and nothing else. The way
// in is the Sign in button in the app bar. A deck is only reachable from a link its owner sends.
export default function GuestLanding() {
  return (
    <div className="guest">
      <Logo size={80} />
      <h1 className="guest-name">MTG Deck Doctor</h1>
      <p className="guest-tagline">The AI-powered deck builder for Commander.</p>
      <div className="guest-features">
        {FEATURES.map((f) => (
          <div key={f.title} className="guest-feature">
            <h2>{f.title}</h2>
            <p>{f.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
