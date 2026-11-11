import type { Hub } from "./api";

type Release = NonNullable<Hub["latest_sets"]>["releases"][number];

// A release's main set, not its Commander set: "Reality Fracture", not
// "Reality Fracture Commander".
export function releaseName(release: Release): string {
  return release.title;
}

// The releases the Doctor looks through, newest first.
export function releaseNames(hub: Hub): string[] {
  return hub.latest_sets?.releases.map(releaseName) ?? [];
}

// Scryfall's search for every card that is new in a release: from its main set or its Commander
// set, not a reprint, and legal in Commander.
export function newCardsQuery(release: Release): string {
  return `(${release.sets.map((s) => `set:${s.code}`).join(" or ")}) -is:reprint legal:commander`;
}

// The card search results page for a release's new cards.
export function newCardsPath(release: Release): string {
  return `/search/results?${new URLSearchParams({ q: newCardsQuery(release), page: "1" })}`;
}
