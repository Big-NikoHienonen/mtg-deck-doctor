import type { ImgHTMLAttributes } from "react";
import type { ImageVersion } from "./api";
import { cardImageUrl, type SelectedPrinting } from "./printings";

// A card's art, or — until its Scryfall id is known — a same-shaped empty
// frame, so the layout doesn't jump and nothing renders as a broken image.
// Ids come from the backend's card cache (which already holds one for every
// card that's ever been in a deck), search results, or EDHREC's payload.
export default function CardImage({
  cardId,
  printing,
  version = "normal",
  alt,
  style,
  ...rest
}: {
  cardId: string | null | undefined;
  printing?: SelectedPrinting;
  version?: ImageVersion;
  alt: string;
} & Omit<ImgHTMLAttributes<HTMLImageElement>, "src" | "alt">) {
  const src = cardImageUrl(cardId, printing, version);
  if (!src) {
    return (
      <div
        role="img"
        aria-label={alt}
        title={rest.title}
        style={{ aspectRatio: "488 / 680", background: "var(--surface)", ...style }}
      />
    );
  }
  return <img src={src} alt={alt} style={style} {...rest} />;
}
