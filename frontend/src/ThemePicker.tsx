import { useEffect, useRef, useState } from "react";
import { THEMES, useTheme } from "./themes";
import "./themepicker.css";

// A small control in the app bar: pick the plane the app looks like.
export default function ThemePicker() {
  const [id, setTheme] = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current = THEMES.find((t) => t.id === id) ?? THEMES[0];

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    window.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div className="tp" ref={ref}>
      <button className="tp-trigger" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="tp-dots" aria-hidden>
          {[current.colors.bg, current.colors.accent, current.colors.accentGold].map((c, i) => (
            <i key={i} style={{ background: c }} />
          ))}
        </span>
        <span className="tp-name">{current.name}</span>
      </button>
      {open && (
        <div className="tp-panel" role="dialog" aria-label="Choose a theme">
          <div className="tp-head">Choose a plane</div>
          <div className="tp-grid">
            {THEMES.map((t) => (
              <button key={t.id} className="tp-card" aria-pressed={t.id === id} onClick={() => setTheme(t.id)}>
                <span className="tp-swatch" aria-hidden>
                  {[t.colors.bg, t.colors.surface, t.colors.accent, t.colors.accentGold].map((c, i) => (
                    <i key={i} style={{ background: c }} />
                  ))}
                </span>
                <strong style={{ fontFamily: t.colors.titleFont, fontWeight: t.colors.titleWeight }}>{t.name}</strong>
                <span className="tp-blurb">{t.blurb}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
