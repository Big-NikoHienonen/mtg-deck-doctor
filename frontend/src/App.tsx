import { Navigate, Route, Routes, useParams } from "react-router-dom";
import HubView from "./HubView";
import DeckView from "./DeckView";
import CardSearchPage from "./CardSearchPage";
import DeckStudio from "./DeckStudio";
import CardSearchResultsPage from "./CardSearchResultsPage";

// Builds were once at /build/:id; they are part of the studio now.
function OldBuildLink() {
  const { buildId } = useParams();
  return <Navigate to={`/new/${buildId}`} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HubView />} />
      <Route path="/decks/:deckId" element={<DeckView />} />
      <Route path="/new/:buildId?" element={<DeckStudio />} />
      <Route path="/build/:buildId" element={<OldBuildLink />} />
      <Route path="/search" element={<CardSearchPage />} />
      <Route path="/search/results" element={<CardSearchResultsPage />} />
    </Routes>
  );
}
