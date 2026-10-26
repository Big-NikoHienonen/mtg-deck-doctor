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
