import { scryfallManaSymbolUrl } from "./api";

export default function ManaPips({ colors, size = 16 }: { colors: string[]; size?: number }) {
  if (colors.length === 0) return null;
  return (
    <span style={{ display: "inline-flex", gap: 3, verticalAlign: "middle" }}>
      {colors.map((c) => (
        <img
          key={c}
          src={scryfallManaSymbolUrl(c)}
          alt={c}
          title={c}
          style={{ width: size, height: size, display: "inline-block" }}
        />
      ))}
    </span>
  );
}
