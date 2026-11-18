#!/usr/bin/env python3
"""歌词抓取层：网易云 / MusicBrainz / lrclib，按时长与名字挑选，编排 get_lrc。"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from nihonco_yomi.config import LY as CFG
from nihonco_yomi.paths import CACHE, ROOT

from .lyrics_cache import cache_path, _cached, write_local_lrc
from .lyrics_text import (_match, _norm, content_lines, is_excluded, is_likely_song,
                          lang_guess, split_name)
from .lyrics_text import TIMED as TS

UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"}
def _get(url: str, timeout: int = 10) -> str:
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def netease(title: str, artist: str) -> dict | None:
    q = f"{title} {artist}".strip()
    r = _get("https://music.163.com/api/search/get?" + urllib.parse.urlencode({"s": q, "type": 1, "limit": 5}))
    try:
        songs = json.loads(r)["result"]["songs"]
    except Exception:
        return None
    for s in songs:
        if not _match(title, s.get("name", "")) or is_excluded(s.get("name", "")):
            continue
        lr = _get(f"https://music.163.com/api/song/lyric?id={s['id']}&lv=-1&kv=-1&tv=-1")
        try:
            j = json.loads(lr)
            lyr = j.get("lrc", {}).get("lyric", "") or ""
            tl = j.get("tlyric", {}).get("lyric", "") or ""   # 中文翻译，一行一句
        except Exception:
            continue
        if TS.search(lyr) and content_lines(lyr) >= CFG["min_content_lines"]:
            lang, ratio = lang_guess(lyr)
            return {"source": "netease", "lang": lang, "kana_ratio": ratio, "tlyric": tl, "id": s["id"], "name": s.get("name", ""),
                    "artist": ", ".join(a["name"] for a in s.get("artists", [])), "lrc": lyr}
    return None


def search_candidates(title: str, artist: str, limit: int = 8) -> list[dict]:
    """多路搜索 + 详情，返回带时长的候选。"""
    ids: list[int] = []
    for q in (f"{title} {artist}".strip(), title, f"{artist} {title}".strip()):
        r = _get("https://music.163.com/api/search/get?" + urllib.parse.urlencode({"s": q, "type": 1, "limit": 8}))
        try:
            for x in json.loads(r)["result"]["songs"]:
                if x["id"] not in ids:
                    ids.append(x["id"])
        except Exception:
            continue
        if len(ids) >= limit * 2:
            break
    ids = ids[:20]
    if not ids:
        return []
    r = _get("https://music.163.com/api/song/detail?ids=" + json.dumps(ids, separators=(",", ":")))   # 方括号不能转义
    out = []
    try:
        for x in json.loads(r).get("songs", []):
            out.append({"id": x["id"], "name": x.get("name", ""),
                        "artist": ", ".join(a["name"] for a in x.get("artists", [])),
                        "duration": round((x.get("duration") or 0) / 1000, 1),
                        "album": (x.get("album") or {}).get("name", "")})
    except Exception:
        pass
    return out


def score_candidate(c: dict, title: str, artist: str, duration: float) -> float:
    s = CFG["weights"]["title"] * (1.0 if _match(title, c["name"]) else 0.0) \
        + CFG["weights"]["artist"] * (1.0 if _match(artist or "x", c["artist"]) else 0.0)
    if duration and c["duration"]:
        d = abs(c["duration"] - duration)
        t3, t10, t30 = CFG["delta_tiers"]
        s += CFG["weights"]["duration"] * (1.0 if d <= t3 else 0.7 if d <= t10 else 0.3 if d <= t30 else 0.0)
    return round(s, 1)


def mb_canonical(title: str, artist: str, duration: float, max_delta: float | None = None) -> dict | None:
    max_delta = CFG["mb_max_delta"] if max_delta is None else max_delta
    """用 MusicBrainz 把歌名规范化：取分数最高、且时长与本地吻合的录音。"""
    if not duration:
        return None
    r = None
    for attempt in range(2):                  # 失败重试一次（扫描时间长，偶发超时）
        try:
            import musicbrainzngs as mb
            mb.set_useragent("nihonco-uta", "0.1", "local")
            r = mb.search_recordings(recording=title, artist=artist or None, limit=8)
            break
        except Exception:
            r = None
            time.sleep(2)
    if r is None:
        return None
    cands = []
    for rec in r.get("recording-list", []):
        L = int(rec.get("length", 0) or 0) / 1000.0
        if not L or abs(L - duration) > max_delta:
            continue
        name = rec.get("title", "")
        if is_excluded(name) or not _match(title, name):   # 名字对不上 = 不是同一首
            continue
        a = ", ".join(x["artist"]["name"] for x in rec.get("artist-credit", [])
                      if isinstance(x, dict) and "artist" in x)
        cands.append({"title": name, "artist": a, "length": L,
                      "score": int(rec.get("ext:score", 0) or 0)})
    if not cands:
        return None
    cands.sort(key=lambda c: (-c["score"], abs(c["length"] - duration)))
    return cands[0]


def lrclib(title: str, artist: str) -> dict | None:
    r = _get("https://lrclib.net/api/search?" + urllib.parse.urlencode({"track_name": title, "artist_name": artist}))
    try:
        rows = json.loads(r)
    except Exception:
        return None
    for x in rows:
        if x.get("syncedLyrics") and _match(title, x.get("trackName", "")):
            lang, ratio = lang_guess(x["syncedLyrics"])
            return {"source": "lrclib", "lang": lang, "kana_ratio": ratio, "id": x.get("id"), "name": x.get("trackName", ""),
                    "artist": x.get("artistName", ""), "lrc": x["syncedLyrics"]}
    return None


def audio_duration(path) -> float:
    """本地音频时长（秒）；读不出来返回 0。"""
    try:
        from mutagen import File
        f = File(str(path))
        return float(f.info.length) if f and f.info else 0.0
    except Exception:
        return 0.0


def best_by_duration(title: str, artist: str, duration: float,
                     max_delta: float | None = None) -> dict | None:
    max_delta = CFG["fallback_max_delta"] if max_delta is None else max_delta
    """默认匹配：按 (标题, 歌手, 时长) 打分挑最可能的版本。"""
    cands = search_candidates(title, artist)
    if not cands:
        return None
    for c in cands:
        c["score"] = score_candidate(c, title, artist, duration)
    cands.sort(key=lambda c: -c["score"])
    for c in cands[:5]:
        if is_excluded(c["name"]):
            continue
        if not _match(title, c["name"]):      # 歌名必须对得上，否则同歌手同长度会错配
            continue
        if c["duration"] and duration and abs(c["duration"] - duration) > max_delta:
            continue                      # 明显是别的版本（TV size / live）
        lr = _get(f"https://music.163.com/api/song/lyric?id={c['id']}&lv=-1&kv=-1&tv=-1")
        try:
            j = json.loads(lr)
        except Exception:
            continue
        lyr = j.get("lrc", {}).get("lyric", "") or ""
        if not TS.search(lyr) or content_lines(lyr) < 3:
            continue
        lang, ratio = lang_guess(lyr)
        return {"source": "netease", "id": c["id"], "name": c["name"], "artist": c["artist"],
                "duration": c["duration"], "score": c["score"],
                "tlyric": j.get("tlyric", {}).get("lyric", "") or "",
                "lang": lang, "kana_ratio": ratio, "lrc": lyr}
    return None


def get_lrc(title: str, artist: str, use_cache: bool = True, duration: float = 0.0,
            force: bool = False) -> dict | None:
    p = cache_path(title, artist)
    if use_cache and not force and p.exists():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
            # 旧缓存没按时长匹配过 → 重算一次
            if not duration or old.get("duration") or old.get("miss"):
                return old
        except Exception:
            pass
    hit, why = None, "no_candidate"
    if duration:
        canon = mb_canonical(title, artist, duration)      # ① MB 规范名
        if canon:
            hit = best_by_duration(canon["title"], canon["artist"], duration)
            if hit:
                hit["via"] = "mb"
            else:
                why = "netease_no_match"
        else:
            why = "mb_no_candidate"
        if not hit:
            hit = best_by_duration(title, artist, duration)
    if not hit:
        hit = netease(title, artist) or lrclib(title, artist)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 失败也缓存，避免每次启动都重新联网（负缓存）
    p.write_text(json.dumps({**hit, "title": title, "artist_q": artist} if hit else {"miss": True, "reason": why},
                            ensure_ascii=False), encoding="utf-8")
    return hit


def scan(folder: Path, force: bool = False, only_cached: bool = False) -> None:
    files = sorted({p.stem for p in folder.rglob("*")
                    if p.suffix.lower() in (".mp3", ".flac", ".wav") and JP.search(p.stem)})
    songs = [s for s in files if is_likely_song(s)]
    if only_cached:                     # 只重扫"本来就有歌词"的歌
        keep = []
        for stem in songs:
            a, t = split_name(stem)
            if _cached(t, a):
                keep.append(stem)
        songs = keep
    print(f"日文名文件 {len(files)}，疑似有人声 {len(songs)}")
    if not songs:
        print("没有可匹配的歌")
        return
    hits, miss = [], []
    by_stem = {}
    for f in folder.rglob("*"):
        if f.suffix.lower() in (".mp3", ".flac", ".wav"):
            by_stem.setdefault(f.stem, f)
    for i, stem in enumerate(songs, 1):
        artist, title = split_name(stem)
        dur = audio_duration(by_stem.get(stem, ""))   # 默认匹配按时长挑版本
        hit = get_lrc(title, artist, duration=dur, force=force)
        (hits if hit else miss).append((stem, hit))
        print(f"{i:3d}/{len(songs)} {'✓' if hit else '✗'} {stem[:46]}", flush=True)
        time.sleep(0.2)
    rep = ROOT / "eval" / "reports" / "lyrics_coverage.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# 歌词获取覆盖\n", f"疑似歌曲 {len(songs)}，拿到 LRC {len(hits)}（{len(hits)/len(songs):.0%}）\n",
             "\n## 已拿到\n", "| 文件 | 来源 | 匹配到的曲名 |", "|---|---|---|"]
    for stem, h in hits:
        lines.append(f"| {stem} | {h.get('source','?')} | {h.get('name','')} |")
    lines += ["\n## 没拿到\n", "| 文件 |", "|---|"]
    lines += [f"| {stem} |" for stem, _ in miss]
    rep.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n覆盖 {len(hits)}/{len(songs)} = {len(hits)/len(songs):.0%} → {rep}")


if __name__ == "__main__":
    if "--scan" in sys.argv:
        scan(Path(sys.argv[sys.argv.index("--scan") + 1]).expanduser(),
             force="--force" in sys.argv, only_cached="--only-cached" in sys.argv)
    elif "--song" in sys.argv:
        i = sys.argv.index("--song")
        h = get_lrc(sys.argv[i + 2], sys.argv[i + 1])
        print(json.dumps(h, ensure_ascii=False, indent=2)[:800] if h else "没找到")


# ── LRC 解析（从播放器挪过来，归数据层）──────────────────


def fetch_lrc_by_id(song_id) -> str:
    """按网易云歌曲 id 取 LRC 文本（用户手动选择候选时用）。"""
    lr = _get(f"https://music.163.com/api/song/lyric?id={song_id}&lv=-1&kv=-1&tv=-1")
    try:
        return json.loads(lr).get("lrc", {}).get("lyric", "") or ""
    except Exception:
        return ""
