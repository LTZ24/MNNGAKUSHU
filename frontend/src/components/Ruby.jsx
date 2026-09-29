import React from "react";

const KANJI_RUN = /([\u3400-\u4dbf\u4e00-\u9fff々〆ヶ]+)/;
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Split "起きます|おきます" into [{起,お},{きます}] so okurigana isn't duplicated in furigana.
export function splitOkurigana(text, reading) {
  if (!reading || reading === text) return [{ text, reading: null }];
  const parts = text.split(KANJI_RUN).filter(Boolean);
  if (!parts.some((p) => KANJI_RUN.test(p))) return [{ text, reading: null }];
  if (parts.length === 1) return [{ text, reading }];
  const pattern = parts.map((p) => (KANJI_RUN.test(p) ? "(.+?)" : escapeRe(p))).join("");
  const m = reading.match(new RegExp(`^${pattern}$`));
  if (!m) return [{ text, reading }];
  let g = 1;
  return parts.map((p) => (KANJI_RUN.test(p) ? { text: p, reading: m[g++] } : { text: p, reading: null }));
}

export function Ruby({ segments = [], size = "base", className = "" }) {
  const sizeCls = size === "lg" ? "text-2xl md:text-3xl" : size === "sm" ? "text-base" : "text-xl";
  const parts = segments.flatMap((seg) => splitOkurigana(seg.text, seg.reading));
  return (
    <span className={`ja-ruby ${sizeCls} ${className}`}>
      {parts.map((seg, i) =>
        seg.reading ? (
          <ruby key={i}>
            {seg.text}
            <rt>{seg.reading}</rt>
          </ruby>
        ) : (
          <span key={i}>{seg.text}</span>
        )
      )}
    </span>
  );
}

export function plainText(segments = []) {
  return segments.map((s) => s.text).join("");
}
