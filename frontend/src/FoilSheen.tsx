import "./foil.css";

// The shimmer over a card that's used as a foil. Goes inside a positioned box
// that is the same size as the card's art; `radius` is the art's corner radius.
export default function FoilSheen({ radius = "4.5% / 3.2%" }: { radius?: string | number }) {
  return <span className="foil-sheen" aria-hidden style={{ borderRadius: radius }} />;
}
