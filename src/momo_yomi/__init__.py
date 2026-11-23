#!/usr/bin/env python3
"""对外接口：一个类 + 一个函数。

    from api import Annotator
    an = Annotator()                       # 载表一次，之后复用
    r = an.annotate("今日は雨が降る")
    r["romaji"]["text"]                    # kyoo wa ame ga furu

也可以直接：annotate("今日は") → dict
"""
from __future__ import annotations

import sys

def _engine():
    # 注意：包内有个同名函数 annotate(text)，`from . import annotate` 会拿到函数，
    # 所以这里必须用 importlib 取模块
    import importlib
    return importlib.import_module(__name__ + ".annotate")


DEFAULT_LAYERS = ["ruby", "romaji", "keys"]


class Annotator:
    """一个进程内复用的标注器。载表一次，之后每次 annotate 只做计算。"""

    def __init__(self, layers: list[str] | None = None, llm: bool = False,
                 emit: str = "B") -> None:
        self.layers = list(layers or DEFAULT_LAYERS)
        _engine().CONFIG.llm = llm
        _engine().CONFIG.emit = emit
        _engine().load_tables()

    def annotate(self, text: str, overrides: dict | None = None) -> dict:
        """标一段文本。overrides 可改读音，罗马音/键位会跟着重算。

        overrides 的键：  "w:床" → 这个词的所有出现
                         "o:0-3" → 第 0 行第 3 个词
        值：平假名读音。
        """
        r = _engine().annotate({"text": text, "layers": self.layers})
        if overrides:
            self._apply_overrides(r, overrides)
        return r

    def _apply_overrides(self, r: dict, overrides: dict) -> None:
        by_word = {k[2:]: v for k, v in overrides.items() if k.startswith("w:")}
        by_occ = {k[2:]: v for k, v in overrides.items() if k.startswith("o:")}
        for li, line in enumerate(r["lines"]):
            segs = line["segments"]
            touched = False
            for seg in segs:
                want = None
                if f"{li}-{seg.get('word')}" in by_occ:
                    want = by_occ[f"{li}-{seg.get('word')}"]
                elif seg.get("wordbase") in by_word:
                    want = by_word[seg["wordbase"]]
                if want:
                    touched = True
                    seg["_ov"] = want
            if not touched:
                continue
            # 把整词的读音按片段切开（赤ん坊 → あか / ぼう）
            for seg in segs:
                if "_ov" not in seg:
                    continue
            for word in {s.get("word") for s in segs if "_ov" in s}:
                members = [s for s in segs if s.get("word") == word and s.get("ruby")]
                if not members:
                    continue
                want = members[0]["_ov"]
                parts = _engine().split_pieces(members[0].get("wordbase") or members[0]["base"], want)
                rubies = [p[1] for p in parts if p and p[1]] if parts else [want]
                for i, m in enumerate(members):
                    m["ruby"] = rubies[i] if i < len(rubies) else ""
            for seg in segs:
                seg.pop("_ov", None)
            segs, romaji_line, keys_line = _engine().add_reading_layers(line["text"], segs)
            line["segments"] = segs
            if "romaji" in r:
                r["romaji"]["lines"][li] = romaji_line
            if "keys" in r:
                r["keys"]["lines"][li] = keys_line
        if "romaji" in r:
            r["romaji"]["text"] = "\n".join(r["romaji"]["lines"])
        if "keys" in r:
            r["keys"]["text"] = "\n".join(r["keys"]["lines"])

    def annotate_lines(self, text: str) -> list[dict]:
        """只取逐行结果，方便直接遍历。"""
        return self.annotate(text)["lines"]

    def reading(self, text: str) -> str:
        """整段的假名读音（用 ruby 拼，K 段用原假名）。"""
        out = []
        for line in self.annotate(text)["lines"]:
            out.append("".join(s.get("ruby") or s["base"] for s in line["segments"]))
        return "\n".join(out)


def annotate(text: str, layers: list[str] | None = None) -> dict:
    """模块级便捷函数：每次调用创建一个 Annotator。"""
    return Annotator(layers=layers).annotate(text)


if __name__ == "__main__":
    an = Annotator()
    sample = sys.argv[1] if len(sys.argv) > 1 else "今日は雨が降る"
    r = an.annotate(sample)
    print("ruby  ", "".join(s.get("ruby") or s["base"] for s in r["lines"][0]["segments"]))
    print("romaji", r["romaji"]["text"])
    print("keys  ", r["keys"]["text"])
