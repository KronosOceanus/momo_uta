#!/usr/bin/env python3
"""把歌词缓存文件重命名到新的（NFKC 归一）键上。

一次性迁移：旧键没做 Unicode 归一，同一个名字的不同写法会产生两个文件，
导致「明明抓到了却查不到」。跑一次即可。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from momo_player.core import lyrics as LY
from momo_player.core.lyrics_cache import CACHE


def main() -> None:
    moved = kept = 0
    for p in list(CACHE.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = d.get("title") or d.get("name") or ""
        artist = d.get("artist_q") or ""
        if not title:
            kept += 1
            continue
        artist = LY.clean_artist(artist) if artist else artist   # 歌手去重后键会变
        target = LY.cache_path(title, artist)
        if target.name == p.name:
            kept += 1
            continue
        if target.exists():          # 新键已有 → 保留较新的那份
            p.unlink()
        else:
            p.rename(target)
            moved += 1
    print(f"迁移完成：重命名 {moved}，未变 {kept}")


if __name__ == "__main__":
    main()
