#!/usr/bin/env python3
"""基线：只用 Sudachi 的读音，不加任何规则/表。

用来回答"我们的规则链比单用分词器好多少"。
用法：同一个 stdio 协议，`python tools/annotate_sudachi.py --stdio [--mode C]`
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from momo_yomi.kana import kata_to_hira  # noqa: E402
from momo_yomi.annotate import split_pieces  # noqa: E402

KANJI = re.compile(r"[\u4e00-\u9fff\u3005\u3006]")
_TOK = None
MODE = "C"


def tokenizer():
    global _TOK
    if _TOK is None:
        from sudachipy import dictionary
        _TOK = dictionary.Dictionary().tokenizer(mode=MODE)
    return _TOK


def annotate_line(line: str) -> dict:
    segs = []
    for i, m in enumerate(tokenizer().tokenize(line)):
        surface = m.surface()
        b, e = m.begin(), m.end()
        if not KANJI.search(surface):
            segs.append({"base": surface, "start": b, "end": e, "word": i,
                         "ruby": None, "level": "K"})
            continue
        reading = kata_to_hira(m.reading_form())
        pieces = split_pieces(surface, reading) if reading else None
        if pieces is None:
            segs.append({"base": surface, "start": b, "end": e, "word": i,
                         "ruby": None, "level": "C", "reason": {"code": "align"}})
            continue
        pos = b
        for text, ruby in pieces:
            segs.append({"base": text, "start": pos, "end": pos + len(text), "word": i,
                         "ruby": ruby, "level": "A" if ruby else "K",
                         "source": "sudachi"})
            pos += len(text)
    return {"text": line, "segments": segs}


def main() -> None:
    global MODE
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdio", action="store_true")
    ap.add_argument("--mode", default="C", choices=["A", "B", "C"])
    a = ap.parse_args()
    MODE = a.mode
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        req = json.loads(raw)
        out = annotate_line(str(req.get("text") or ""))
        out["version"] = {"engine": "sudachi", "mode": MODE}
        print(json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
