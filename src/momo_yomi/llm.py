"""LLM 消歧客户端：只做「从候选里选一个读音」这一件事。

设计纪律（抄 JRM 的做法）：**不让模型自由生成**，输出必须是候选集合里的一个，
否则一律视为失败并由调用方弃权（C）。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request

from .common import CACHE as _CACHE, ROOT
CACHE = _CACHE / "llm"
ENDPOINT = "https://api.deepseek.com/chat/completions"
MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

SYSTEM = """你是日语振假名标注器。任务：判断句子中【方括号】里那段汉字，在这句话里读什么。

规则：
1. 只能从候选读音里选，禁止创造候选之外的读音。
2. 必须看整句：同一个词在不同语境里读音不同
   （生ビール=なま / 生きる=い / 生涯=しょうがい；何時ですか=なんじ / 何時来る=いつ）。
3. 读音必须只对应【】里的汉字，不能把后面的送り仮名读进来。
4. 确实无法判断就返回 null，不要猜。
5. 同时给出 0–1 的置信度：常见搭配、语境明确就给 0.9 以上；多解、靠猜给 0.6 以下。
6. 只输出 JSON，不要解释。"""


def api_key() -> str:
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("没有 DEEPSEEK_API_KEY（放 .env 或环境变量）")


def _post(payload: dict, tries: int = 3, timeout: int = 60) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(
                ENDPOINT, data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {api_key()}"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("unreachable")


def cache_key(text: str, idx: int, base: str, cands: list[str]) -> str:
    raw = f"{text}\u0000{idx}\u0000{base}\u0000{'|'.join(cands)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def load_cache() -> dict[str, str]:
    f = CACHE / "choices.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict[str, str]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "choices.json").write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def choose_batch(items: list[dict], temperature: float = 0) -> dict[int, str | None]:
    """items: [{"text","idx","base","cands"}] → {items 下标: 选中读音或 None}"""
    payload_items = []
    for i, it in enumerate(items):
        t, s0 = it["text"], it["idx"]
        marked = t[:s0] + "【" + t[s0:s0 + len(it["base"])] + "】" + t[s0 + len(it["base"]):]
        payload_items.append({"i": i, "sentence": marked, "candidates": it["cands"]})
    user = ("判断每个句子里【】中汉字的读音。\n"
            + json.dumps(payload_items, ensure_ascii=False)
            + '\n只输出形如 [{"i":0,"reading":"なま","conf":0.95}] 的 JSON 数组；无法判断用 null。')

    resp = _post({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": 800 + 200 * len(items),
    })
    content = resp["choices"][0]["message"]["content"].strip()
    out: dict[int, tuple[str, float]] = {}
    try:
        start, end = content.find("["), content.rfind("]")
        arr = json.loads(content[start:end + 1]) if start >= 0 and end > start else []
    except json.JSONDecodeError:
        arr = []
    for row in arr:
        try:
            i = int(row["i"])
            r = row.get("reading")
            c = float(row.get("conf", 0.5))
        except (KeyError, TypeError, ValueError):
            continue
        if i in range(len(items)) and isinstance(r, str) and r in items[i]["cands"]:
            out[i] = (r, c)
    return out
