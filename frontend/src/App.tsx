import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";
import AdminPage from "./AdminPage";
import AppBar from "./AppBar";
import AuthGate from "./AuthGate";
import BrowsePage from "./BrowsePage";
import { refreshAuth } from "./authStore";
import DeckRoute from "./DeckRoute";
import DecksPage from "./DecksPage";
import LandingView from "./LandingView";
import LoginPage from "./LoginPage";
import Snackbar from "./Snackbar";
import ProfilePage from "./ProfilePage";
import CardSearchPage from "./CardSearchPage";
import CardSearchResultsPage from "./CardSearchResultsPage";
import "./mobile.css"; // Last, so it wins over the pages' own styles where they overlap.

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
          <Route path="/login" element={<LoginPage />} />
          <Route path="/browse" element={<BrowsePage />} />
          <Route path="/decks/:deckId" element={<DeckRoute />} />
          <Route element={<AuthGate />}>
            <Route path="/" element={<LandingView />} />
            <Route path="/decks" element={<DecksPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/search" element={<CardSearchPage />} />
            <Route path="/search/results" element={<CardSearchResultsPage />} />
          </Route>
        </Routes>
      </main>
      <Snackbar />
    </>
  );
}
