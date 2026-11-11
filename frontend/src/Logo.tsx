// The app's mark: two cards, the front one marked with a cross. It takes the theme's colors, so it
// matches whichever plane is chosen. public/favicon.svg is the same drawing in the default colors.
export default function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect x="9" y="3" width="17" height="24" rx="3" transform="rotate(14 17.5 15)" fill="var(--accent-gold)" />
      <g transform="rotate(-8 14.5 17)">
        <rect x="6" y="5" width="17" height="24" rx="3" fill="var(--accent)" />
        <rect x="12.9" y="11" width="3.2" height="12" rx="1" fill="var(--on-accent)" />
        <rect x="8.5" y="15.4" width="12" height="3.2" rx="1" fill="var(--on-accent)" />
      </g>
    </svg>
  );
}
