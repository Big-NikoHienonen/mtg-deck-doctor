import { Link } from "react-router-dom";
import type { Hub } from "./api";
import { newCardsPath, releaseName } from "./releases";
import { buttonStyle, eyebrowStyle } from "./styles";

// A way to every new card in the latest releases, not only the ones the Doctor picked: one link per
// release, to the card search results for it. It shows whenever the releases are known, whether or
// not the Doctor has picks.
export default function NewSetLinks({ hub }: { hub: Hub }) {
  const releases = hub.latest_sets?.releases ?? [];
  if (releases.length === 0) return null;
  return (
    <nav aria-label="All new cards" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 }}>
      <div style={{ ...eyebrowStyle, marginBottom: 0 }}>ALL NEW CARDS FROM</div>
      {releases.map((release) => (
        <Link
          key={release.released_at}
          to={newCardsPath(release)}
          className="btn"
          style={{ ...buttonStyle, textDecoration: "none", display: "inline-block" }}
        >
          {releaseName(release)} →
        </Link>
      ))}
    </nav>
  );
}
