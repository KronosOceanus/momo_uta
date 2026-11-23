#!/usr/bin/env python3
"""歌词抓取层：网易云候选，自动与手动共用过滤、校验和挑选。"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from momo_yomi.config import LY as CFG

from . import fsio as FS

from .lyrics_cache import cache_path
from .lyrics_text import _match, content_lines, has_timed, is_excluded, lang_guess

UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"}
MATCH_OK = "ok"
MATCH_NO_MATCH = "no_match"
MATCH_NO_LYRICS = "no_lyrics"
MATCH_NETWORK = "network_error"


class LyricsNetworkError(RuntimeError):
    pass
def _get(url: str, timeout: float | None = None) -> str:
    timeout = float(CFG["http_timeout_s"]) if timeout is None else timeout
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def search_candidates(title: str, artist: str, limit: int | None = None) -> list[dict]:
    """多路搜索；搜索结果本身已带歌手/时长，不再请求 detail。

    没有任何一个查询得到合法响应时抛 LyricsNetworkError，调用方不要把它
    当成“确实没有”。
    """
    limit = int(CFG["search_limit"]) if limit is None else limit
    found: dict[int, dict] = {}
    got_response = False
    for q in (f"{title} {artist}".strip(), title, f"{artist} {title}".strip()):
        r = _get("https://music.163.com/api/search/get?" + urllib.parse.urlencode(
            {"s": q, "type": 1, "limit": limit}))
        if not r:
            continue
        try:
            data = json.loads(r)
            songs = data["result"]["songs"]
        except Exception:
            continue
        if not isinstance(songs, list):
            continue
        got_response = True
        for x in songs:
            try:
                song_id = int(x["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if song_id in found:
                continue
            artists = x.get("artists") or []
            found[song_id] = {
                "id": song_id,
                "name": x.get("name", ""),
                "artist": ", ".join(a.get("name", "") for a in artists
                                    if isinstance(a, dict) and a.get("name")),
                "duration": round(float(x.get("duration") or 0) / 1000, 1),
                "album": (x.get("album") or {}).get("name", ""),
            }
        if len(found) >= limit * 2:
            break
    if not got_response:
        raise LyricsNetworkError("网络请求失败")
    return list(found.values())[:int(CFG["max_ids"])]


def search_candidates_status(title: str, artist: str,
                             limit: int | None = None) -> tuple[list[dict], str]:
    try:
        rows = search_candidates(title, artist, limit)
    except LyricsNetworkError:
        return [], MATCH_NETWORK
    return rows, (MATCH_OK if rows else MATCH_NO_MATCH)


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


def auto_match_status(title: str, artist: str,
                      duration: float) -> tuple[dict | None, str]:
    """自动匹配；返回 (hit, status)，status 区分无候选/无可用歌词/网络错误。"""
    try:
        cands, status = search_candidates_status(title, artist)
    except LyricsNetworkError:
        return None, MATCH_NETWORK
    if status != MATCH_OK:
        return None, status
    for c in cands:
        c["score"] = score_candidate(c, title, artist, duration)
    cands.sort(key=lambda c: -c["score"])
    for c in cands[:int(CFG["auto_try"])]:
        if not accept_candidate(c, title, artist, duration):
            continue
        hit = fetch_candidate(c)
        if hit:
            return hit, MATCH_OK
    return None, MATCH_NO_LYRICS


def auto_match(title: str, artist: str, duration: float) -> dict | None:
    return auto_match_status(title, artist, duration)[0]


def _negative_fresh(old: dict, path: Path) -> bool:
    ttl = float(CFG.get("negative_ttl_days", 7) or 0) * 86400
    if ttl <= 0 or not old.get("miss"):
        return False
    checked = old.get("checked_at")
    if checked is None:
        try:
            checked = path.stat().st_mtime
        except OSError:
            return False
    try:
        return time.time() - float(checked) < ttl
    except (TypeError, ValueError):
        return False


def get_lrc_status(title: str, artist: str, use_cache: bool = True,
                   duration: float = 0.0, force: bool = False,
                   network: bool = True) -> tuple[dict | None, str]:
    p = cache_path(title, artist)
    if use_cache and not force and p.exists():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
            old_lrc = old.get("lrc") or ""
            cached_ok = (not old_lrc or valid_lrc(old_lrc))
            if cached_ok and (not duration or old.get("duration") or old.get("miss")):
                if not old.get("miss") or _negative_fresh(old, p):
                    return old, (MATCH_OK if old_lrc else
                                 (old.get("reason") or MATCH_NO_MATCH))
        except Exception:
            pass
    if not network:
        return None, "offline"
    hit, status = auto_match_status(title, artist, duration)
    if status == MATCH_NETWORK:
        return None, status            # 网络失败不写负缓存
    FS.atomic_write_json(p, {**hit, "title": title, "artist_q": artist} if hit else {
        "miss": True, "reason": status, "checked_at": time.time()}, indent=None)
    return hit, status


def get_lrc(title: str, artist: str, use_cache: bool = True, duration: float = 0.0,
            force: bool = False, network: bool = True) -> dict | None:
    return get_lrc_status(title, artist, use_cache, duration, force, network)[0]


def fetch_lyrics_by_id(song_id) -> dict:
    """按网易云歌曲 id 取原文与翻译，一次调用显式返回。"""
    out = {"lrc": "", "tlyric": ""}
    lr = _get(f"https://music.163.com/api/song/lyric?id={song_id}&lv=-1&kv=-1&tv=-1")
    try:
        j = json.loads(lr)
        out["lrc"] = j.get("lrc", {}).get("lyric", "") or ""
        out["tlyric"] = j.get("tlyric", {}).get("lyric", "") or ""
    except Exception:
        pass
    return out
