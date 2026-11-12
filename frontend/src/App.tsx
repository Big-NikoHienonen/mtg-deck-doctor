import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";
import AdminPage from "./AdminPage";
import AppBar from "./AppBar";
import AuthGate from "./AuthGate";
import { refreshAuth } from "./authStore";
import DeckRoute from "./DeckRoute";
import HubView from "./HubView";
import CardSearchPage from "./CardSearchPage";
import CardSearchResultsPage from "./CardSearchResultsPage";

export default function App() {
  // Asked once, here, since the app bar and every page read the answer.
  useEffect(() => {
    refreshAuth();
  }, []);

  return (
    <>
      <AppBar />
      <main className="page">
        <Routes>
          <Route path="/decks/:deckId" element={<DeckRoute />} />
          <Route element={<AuthGate />}>
            <Route path="/" element={<HubView />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/search" element={<CardSearchPage />} />
            <Route path="/search/results" element={<CardSearchResultsPage />} />
          </Route>
        </Routes>
      </main>
    </>
  );
}
