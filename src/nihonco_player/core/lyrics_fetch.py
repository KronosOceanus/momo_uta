#!/usr/bin/env python3
"""歌词抓取层：网易云候选，自动与手动共用过滤、校验和挑选。"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from nihonco_yomi.config import LY as CFG
from nihonco_yomi.paths import CACHE, ROOT

from . import fsio as FS

from .lyrics_cache import cache_path
from .lyrics_text import (_match, content_lines, has_timed, is_excluded,
                          is_likely_song, lang_guess, split_name)

UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"}
def _get(url: str, timeout: float | None = None) -> str:
    timeout = float(CFG["http_timeout_s"]) if timeout is None else timeout
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def search_candidates(title: str, artist: str, limit: int | None = None) -> list[dict]:
    """多路搜索 + 详情，返回带时长的候选。"""
    limit = int(CFG["search_limit"]) if limit is None else limit
    ids: list[int] = []
    for q in (f"{title} {artist}".strip(), title, f"{artist} {title}".strip()):
        r = _get("https://music.163.com/api/search/get?" + urllib.parse.urlencode({"s": q, "type": 1, "limit": limit}))
        try:
            for x in json.loads(r)["result"]["songs"]:
                if x["id"] not in ids:
                    ids.append(x["id"])
        except Exception:
            continue
        if len(ids) >= limit * 2:
            break
    ids = ids[:int(CFG["max_ids"])]
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


def audio_duration(path) -> float:
    """本地音频时长（秒）；读不出来返回 0。"""
    try:
        from mutagen import File
        f = File(str(path))
        return float(f.info.length) if f and f.info else 0.0
    except Exception:
        return 0.0


def valid_lrc(text: str) -> bool:
    """唯一的歌词可用性判断：必须有时间轴、至少 3 行。"""
    return bool(text) and has_timed(text) and content_lines(text) >= CFG["min_content_lines"]


def accept_candidate(c: dict, title: str, artist: str, duration: float,
                     max_delta: float | None = None) -> bool:
    """自动与手动共用的候选元数据过滤。"""
    if not c or not c.get("id"):
        return False
    name = c.get("name", "")
    if not _match(title, name) or is_excluded(name):
        return False
    max_delta = CFG["fallback_max_delta"] if max_delta is None else max_delta
    if c.get("duration") and duration and abs(c["duration"] - duration) > max_delta:
        return False
    return True


def fetch_candidate(c: dict) -> dict | None:
    """按候选 id 抓正文；自动和手动 pick 共用同一套校验。"""
    lr = _get(f"https://music.163.com/api/song/lyric?id={c['id']}&lv=-1&kv=-1&tv=-1")
    try:
        j = json.loads(lr)
    except Exception:
        return None
    lyr = j.get("lrc", {}).get("lyric", "") or ""
    if not valid_lrc(lyr):
        return None
    lang, ratio = lang_guess(lyr)
    return {"source": "netease", "id": c["id"], "name": c.get("name", ""),
            "artist": c.get("artist", ""), "duration": c.get("duration") or 0,
            "score": c.get("score"), "tlyric": j.get("tlyric", {}).get("lyric", "") or "",
            "lang": lang, "kana_ratio": ratio, "lrc": lyr}


def auto_match(title: str, artist: str, duration: float) -> dict | None:
    """自动匹配：和 rematch 用同一批候选、同一套过滤，自动取分数最高。"""
    cands = search_candidates(title, artist)
    if not cands:
        return None
    for c in cands:
        c["score"] = score_candidate(c, title, artist, duration)
    cands.sort(key=lambda c: -c["score"])
    for c in cands[:int(CFG["auto_try"])]:
        if not accept_candidate(c, title, artist, duration):
            continue
        hit = fetch_candidate(c)
        if hit:
            return hit
    return None


def get_lrc(title: str, artist: str, use_cache: bool = True, duration: float = 0.0,
            force: bool = False, network: bool = True) -> dict | None:
    p = cache_path(title, artist)
    if use_cache and not force and p.exists():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
            old_lrc = old.get("lrc") or ""
            cached_ok = (not old_lrc or valid_lrc(old_lrc))
            # 旧缓存没按时长匹配过 → 重算一次；无时间轴的旧结果直接作废
            if cached_ok and (not duration or old.get("duration") or old.get("miss")):
                return old
        except Exception:
            pass
    if not network:                     # 加载路径只读本地；联网只由匹配阶段触发
        return None
    hit = auto_match(title, artist, duration)
    # 失败也缓存，避免每次启动都重新联网（负缓存）
    FS.atomic_write_json(p, {**hit, "title": title, "artist_q": artist} if hit else {"miss": True, "reason": "no_match"},
                         indent=None)
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
        time.sleep(float(CFG["scan_sleep"]))
    rep = ROOT / "eval" / "reports" / "lyrics_coverage.md"
    lines = [f"# 歌词获取覆盖\n", f"疑似歌曲 {len(songs)}，拿到 LRC {len(hits)}（{len(hits)/len(songs):.0%}）\n",
             "\n## 已拿到\n", "| 文件 | 来源 | 匹配到的曲名 |", "|---|---|---|"]
    for stem, h in hits:
        lines.append(f"| {stem} | {h.get('source','?')} | {h.get('name','')} |")
    lines += ["\n## 没拿到\n", "| 文件 |", "|---|"]
    lines += [f"| {stem} |" for stem, _ in miss]
    FS.atomic_write_text(rep, "\n".join(lines))
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
