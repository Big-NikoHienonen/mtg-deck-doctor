import { Route, Routes } from "react-router-dom";
import AdminPage from "./AdminPage";
import HubView from "./HubView";
import DeckView from "./DeckView";
import CardSearchPage from "./CardSearchPage";
import CardSearchResultsPage from "./CardSearchResultsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HubView />} />
      <Route path="/decks/:deckId" element={<DeckView />} />
      <Route path="/admin" element={<AdminPage />} />
      <Route path="/search" element={<CardSearchPage />} />
      <Route path="/search/results" element={<CardSearchResultsPage />} />
    </Routes>
  );
}
