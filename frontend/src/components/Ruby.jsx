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
  if (!m) {
    const kanjiParts = parts.filter((p) => KANJI_RUN.test(p));
    const otherKana = parts.every((p) => KANJI_RUN.test(p) || /^[\u3040-\u30ff]+$/.test(p));
    if (kanjiParts.length !== 1 || !otherKana) return [{ text, reading }];
    return parts.map((p) => ({ text: p, reading: KANJI_RUN.test(p) ? reading : null }));
  }
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

const JA_EDGE = /[\u3000-\u30ff\u3400-\u9fff\uff00-\uffef]/;

// Parse DSL text like "財布|さいふ に 500円|ごひゃくえん" into ruby segments.
export function parseSpec(str = "") {
  const out = [];
  let prev = "";
  for (const token of String(str).split(" ").filter(Boolean)) {
    const needSpace = prev && !(JA_EDGE.test(prev.slice(-1)) && JA_EDGE.test(token[0]));
    if (needSpace) out.push({ text: " ", reading: null });
    const m = token.match(/^(.+?)\|([^\s,、。，]+)(.*)$/);
    if (m) {
      out.push({ text: m[1], reading: m[2] });
      if (m[3]) out.push({ text: m[3], reading: null });
    } else out.push({ text: token, reading: null });
    prev = token;
  }
  return out;
}

const PAREN_READING = /([\u3400-\u4dbf\u4e00-\u9fff々]+)[(（]([\u3040-\u309f]+)[)）]/g;

function parseParen(str) {
  const out = [];
  let last = 0;
  for (const m of str.matchAll(PAREN_READING)) {
    if (m.index > last) out.push({ text: str.slice(last, m.index), reading: null });
    out.push({ text: m[1], reading: m[2] });
    last = m.index + m[0].length;
  }
  if (last < str.length) out.push({ text: str.slice(last), reading: null });
  return out;
}

export function RubyText({ text, size = "sm", className = "" }) {
  if (!text) return <>{text}</>;
  const s = String(text);
  if (s.includes("|")) return <Ruby segments={parseSpec(s)} size={size} className={className} />;
  if (new RegExp(PAREN_READING.source).test(s)) return <Ruby segments={parseParen(s)} size={size} className={className} />;
  return <>{text}</>;
}
