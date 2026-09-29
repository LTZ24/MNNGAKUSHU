"""Iteration 12: Furigana DSL leak checks — library API must never expose '|' markup."""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://gakushu-app-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

PIPE_RE = re.compile(r"\|")


def _walk_for_pipe(obj, path="root"):
    """Recursively walk any JSON structure, return list of 'path=value' where value contains '|'."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            hits += _walk_for_pipe(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _walk_for_pipe(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        # Skip legitimate id strings like "bunpo|1|q1" — quiz uses '|' as internal ID separator;
        # but library endpoints have no such IDs. We only skip 'id' path components.
        if "|" in obj and not path.endswith(".id"):
            hits.append(f"{path} = {obj!r}")
    return hits


@pytest.mark.parametrize("bab", [1, 4, 5, 11, 26, 27, 49])
def test_kotoba_has_no_pipe_markup(bab):
    r = requests.get(f"{API}/library/kotoba", params={"bab": bab}, timeout=30)
    assert r.status_code == 200, r.text
    payload = r.json()
    cards = payload.get("cards", [])
    assert isinstance(cards, list) and len(cards) > 0, f"no kotoba for bab={bab}"
    hits = _walk_for_pipe(payload, f"kotoba_bab{bab}")
    assert not hits, f"Pipe markup leaked in kotoba bab={bab}:\n" + "\n".join(hits[:20])


@pytest.mark.parametrize("bab", [1, 4, 5, 11, 26, 27, 49])
def test_kanji_has_no_pipe_markup(bab):
    r = requests.get(f"{API}/library/kanji", params={"bab": bab}, timeout=30)
    assert r.status_code == 200, r.text
    payload = r.json()
    hits = _walk_for_pipe(payload, f"kanji_bab{bab}")
    assert not hits, f"Pipe markup leaked in kanji bab={bab}:\n" + "\n".join(hits[:20])


@pytest.mark.parametrize("num", [1, 4, 5, 11])
def test_chapter_detail_kaiwa_bunpo_segments_have_no_pipe(num):
    r = requests.get(f"{API}/chapters/{num}", timeout=30)
    assert r.status_code == 200, r.text
    ch = r.json()
    content = ch.get("content") or ch  # depending on shape
    # We accept DSL strings in "keterangan" / "text" fields since RubyText renders them client-side,
    # but STRUCTURED segment lists must NOT contain '|'. We scan segments/*.text / segments/*.reading.
    def scan_segments(obj, path):
        problems = []
        if isinstance(obj, dict):
            if "segments" in obj and isinstance(obj["segments"], list):
                for i, s in enumerate(obj["segments"]):
                    if isinstance(s, dict):
                        t = s.get("text") or ""
                        rd = s.get("reading") or ""
                        if "|" in t:
                            problems.append(f"{path}.segments[{i}].text = {t!r}")
                        if "|" in rd:
                            problems.append(f"{path}.segments[{i}].reading = {rd!r}")
            for k, v in obj.items():
                problems += scan_segments(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                problems += scan_segments(v, f"{path}[{i}]")
        return problems

    seg_hits = scan_segments(content, f"ch{num}")
    assert not seg_hits, "Segments contain pipe markup:\n" + "\n".join(seg_hits[:20])


def test_specific_shiritsu_word_reading_not_doubled():
    """Regression: 私立 must not have kana 'しりつしりつ' anywhere across all chapters."""
    for bab in range(1, 51):
        r = requests.get(f"{API}/library/kotoba", params={"bab": bab}, timeout=30)
        if r.status_code != 200:
            continue
        for card in r.json().get("cards", []):
            kana = card.get("kana") or ""
            # Check duplication pattern: same string repeated twice
            if len(kana) >= 4 and len(kana) % 2 == 0 and kana[: len(kana) // 2] == kana[len(kana) // 2:]:
                # Allow legitimate reduplication like ときどき, いろいろ, etc. — but only Japanese kana
                # We only fail when both halves are >=3 chars (unlikely to be a real reduplication).
                half = len(kana) // 2
                if half >= 3:
                    pytest.fail(f"Suspicious doubled kana bab={bab} word={card.get('word')!r} kana={kana!r}")
