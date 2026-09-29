import React, { useEffect, useState } from "react";

// KanjiVG (free CDN) — stroke paths are listed in stroke order.
const CDN = "https://cdn.jsdelivr.net/gh/KanjiVG/kanjivg@master/kanji";
const cache = new Map();

function loadStrokes(ch) {
  if (!cache.has(ch)) {
    const cp = ch.codePointAt(0).toString(16).padStart(5, "0");
    cache.set(ch, fetch(`${CDN}/${cp}.svg`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error("no svg"))))
      .then((txt) => {
        const paths = [...txt.matchAll(/<path[^>]*\sd="([^"]+)"/g)].map((m) => m[1]);
        if (!paths.length) throw new Error("empty");
        return paths;
      })
      .catch((e) => { cache.delete(ch); throw e; }));
  }
  return cache.get(ch);
}

export function useStrokes(character) {
  const [state, setState] = useState({ status: "loading", paths: [] });
  useEffect(() => {
    if (!character) return;
    let alive = true;
    setState({ status: "loading", paths: [] });
    loadStrokes(character)
      .then((paths) => alive && setState({ status: "ok", paths }))
      .catch(() => alive && setState({ status: "fallback", paths: [] }));
    return () => { alive = false; };
  }, [character]);
  return state;
}

const Grid = () => (
  <g className="kvg-grid">
    <line x1="54.5" y1="0" x2="54.5" y2="109" />
    <line x1="0" y1="54.5" x2="109" y2="54.5" />
  </g>
);

export default function KanjiStroke({ character, size = 220 }) {
  const { status, paths } = useStrokes(character);
  const [playKey, setPlayKey] = useState(0);
  if (status !== "ok") {
    return <div className={`kanji-stroke ${status}`} style={{ width: size, height: size }}>{status === "loading" ? "…" : character}</div>;
  }
  return (
    <div className="kanji-stroke ok" style={{ width: size, height: size }} data-testid={`kanji-stroke-${character}`}>
      <svg viewBox="0 0 109 109" className="kvg-svg" key={playKey}>
        <Grid />
        {paths.map((d, i) => <path key={`g${i}`} d={d} className="kvg-ghost" />)}
        {paths.map((d, i) => (
          <path key={i} d={d} pathLength="1" className="kvg-draw" style={{ animationDelay: `${i * 0.6}s` }} />
        ))}
      </svg>
      <button className="stroke-replay" onClick={() => setPlayKey(playKey + 1)} data-testid="stroke-replay" aria-label="Putar ulang goresan">↻</button>
    </div>
  );
}

export function StrokeSteps({ character }) {
  const { status, paths } = useStrokes(character);
  if (status === "loading") return <div className="muted small">Memuat urutan goresan…</div>;
  if (status !== "ok") return <div className="muted small">Urutan goresan belum tersedia untuk {character}.</div>;
  return (
    <div className="stroke-steps" data-testid={`stroke-steps-${character}`}>
      {paths.map((_, step) => (
        <div className="stroke-step" key={step} data-testid={`stroke-step-${step + 1}`}>
          <svg viewBox="0 0 109 109">
            <Grid />
            {paths.slice(0, step + 1).map((d, i) => (
              <path key={i} d={d} className={i === step ? "kvg-current" : "kvg-done"} />
            ))}
          </svg>
          <span>{step + 1}</span>
        </div>
      ))}
    </div>
  );
}
