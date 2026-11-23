#!/usr/bin/env python3
"""单曲业务：载荷装配、改读音、重新匹配、选候选、懒匹配。

只依赖 core 与引擎；不碰 HTTP。
"""
from __future__ import annotations

import json
import re
import threading

from ..core import annotation_cache as ANN_CACHE
from ..core import library as LIB
from ..core import lrc_files as LRC
from ..core import lrc_doc as DOC
from ..core import diag
from ..core import fsio as FS
from ..core import lyrics as LY
from ..core import song_meta as META
from ..core.annotation import (AN, annotations_from_lines,  # noqa: F401
                               annotate_line_with_notes, annotate_line_with_token_overrides,
                               ruby_html, segs_of, strip_paren_ruby, words_html_of)
from ..core.lrc_doc import new_line_id, new_token_ids, tokens_with_spans

KANA_RE = re.compile(r"[\u3040-\u30ff]")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")
LAT_RE = re.compile(r"[A-Za-z]")




def load_lyrics(item: dict) -> tuple[dict, bool]:
    """普通页与 LRC 编辑共用的唯一歌词入口。"""
    doc = LRC.load(item["file"], item.get("uid"),
                   item["title"], item.get("artist", ""))
    return doc, LRC.usable_doc(doc)


def _annotate_lines(lines, stored=None, reuse=None, old_texts=None,
                    tokens=None, old_token_values=None):
    """按行生成读音；行内正文变化时按 token id 保留读音。"""
    ann = {}
    stored = stored or {}
    reuse = reuse or set()
    old_texts = old_texts or {}
    tokens = tokens or {}
    old_token_values = old_token_values or {}
    for i, ln in enumerate(lines):
        text = (ln.get("text") or "").strip()
        if not text:
            continue
        st = stored.get(i)
        if i in reuse and st and "".join(x[0] for x in st) == text:
            ann[i] = st
            continue
        try:
            line_tokens = tokens.get(i) or []
            if line_tokens and old_token_values:
                ann[i] = segs_of(annotate_line_with_token_overrides(
                    text, line_tokens, old_token_values))
            elif st and old_texts.get(i) not in (None, text):
                from ..core.annotation import annotate_line_preserving_notes
                ann[i] = segs_of(annotate_line_preserving_notes(text, old_texts[i], st))
            else:
                ann[i] = segs_of(annotate_line_with_notes(text, stored=st))
        except Exception as e:
            diag.log("annotate", f"第 {i} 行注音失败：{e}")
    return ann


def _saved_identities(body_rows, ann, line_ids, token_ids):
    """保存响应：把后端新生成的 lid/tid 回传给编辑器。"""
    out = []
    for bi, seg in sorted((ann or {}).items()):
        if bi >= len(body_rows) or not seg:
            continue
        lid = (line_ids or {}).get(bi)
        tids = (token_ids or {}).get(bi) or []
        if not lid or len(tids) != len(seg):
            continue
        payload = body_rows[bi].get("text") or ""
        tokens = tokens_with_spans(seg, tids, payload)
        if tokens:
            out.append({"i": bi, "text": payload,
                        "lid": lid, "tokens": tokens})
    return out


def _body_layout(rows):
    """把编辑器行拆成非空歌词行与 body → lyric 映射。"""
    lyric_rows = []
    body_to_lyric = {}
    for bi, ln in enumerate(rows or []):
        if (ln.get("text") or "").strip():
            body_to_lyric[bi] = len(lyric_rows)
            lyric_rows.append(ln)
    return lyric_rows, body_to_lyric


def _old_save_layout(doc):
    """收集旧文档的 compact/body 标注、身份和 token 值。"""
    old_body_rows = doc.get("body_rows") or doc.get("lines") or []
    _old_lyric_rows, old_body_to_lyric = _body_layout(old_body_rows)
    old_ann = {bi: (doc.get("annotations") or {}).get(li)
               for bi, li in old_body_to_lyric.items()
               if (doc.get("annotations") or {}).get(li)}
    old_lids = {bi: (doc.get("line_ids") or {}).get(li)
                for bi, li in old_body_to_lyric.items()}
    old_tids = {bi: (doc.get("token_ids") or {}).get(li)
                for bi, li in old_body_to_lyric.items()}
    old_texts = {bi: (ln.get("text") or "").strip()
                 for bi, ln in enumerate(old_body_rows)}
    old_token_values = {}
    compact_tids = doc.get("token_ids") or {}
    for i, segs in (doc.get("annotations") or {}).items():
        ids = compact_tids.get(i) or []
        for ti, seg in enumerate(segs):
            if ti < len(ids):
                old_token_values[ids[ti]] = seg
    return {"body_rows": old_body_rows, "body_to_lyric": old_body_to_lyric,
            "ann": old_ann, "lids": old_lids, "tids": old_tids,
            "texts": old_texts, "token_values": old_token_values}


def _map_new_to_old(body_rows, old):
    """新 body 行 → 旧 body 行：lid 优先，文本匹配，最后位置兜底。"""
    used = set()
    mapped = {}
    old_body = old.get("body_rows") or []
    old_by_lid = {lid: bi for bi, lid in (old.get("lids") or {}).items() if lid}

    # 第一轮：能对上的 lid。
    for bi, ln in enumerate(body_rows):
        lid = ln.get("lid")
        old_bi = old_by_lid.get(lid) if lid else None
        if old_bi is not None and old_bi not in used:
            mapped[bi] = old_bi
            used.add(old_bi)

    # 第二轮：没有 lid 的行先按文本匹配，交换/重排也能找回读音。
    for bi, ln in enumerate(body_rows):
        if bi in mapped or ln.get("lid"):
            continue
        text = ln.get("text") or ""
        for old_bi, old_ln in enumerate(old_body):
            if old_bi not in used and (old_ln.get("text") or "") == text:
                mapped[bi] = old_bi
                used.add(old_bi)
                break

    # 第三轮：剩下的、行数不变的无 lid 编辑行才按位置兜底。
    if len(body_rows) == len(old_body):
        for bi, ln in enumerate(body_rows):
            if bi in mapped or ln.get("lid") or bi in used:
                continue
            mapped[bi] = bi
            used.add(bi)
    return mapped


def _tokens_match_old(line, old_bi, old):
    """整行 token 序列与旧 tid/span/base 完全一致时才允许整行快路径。"""
    tokens = line.get("tokens") or []
    old_segs = (old.get("ann") or {}).get(old_bi) or []
    old_ids = (old.get("tids") or {}).get(old_bi) or []
    text = line.get("text") or ""
    if not tokens or len(tokens) != len(old_segs) or len(old_ids) != len(old_segs):
        return False
    pos = 0
    for i, seg in enumerate(old_segs):
        base = str(seg[0] or "")
        end = pos + len(base)
        tok = tokens[i] if i < len(tokens) else None
        if not tok or tok.get("tid") != old_ids[i]:
            return False
        if tok.get("start") != pos or tok.get("end") != end or tok.get("base") != base:
            return False
        if text[pos:end] != base:
            return False
        pos = end
    return pos == len(text)


def _line_reuse(line, old_bi, old):
    """整行复用的唯一判定：注音和 ID 必须共用。"""
    if old_bi is None:
        return False
    st = (old.get("ann") or {}).get(old_bi)
    if not st:
        return False
    if (line.get("text") or "") != (old.get("texts") or {}).get(old_bi, ""):
        return False
    tokens = line.get("tokens") or []
    if not tokens:
        return True
    return _tokens_match_old(line, old_bi, old)


def _build_reuse(body_rows, mapped, old):
    return {bi for bi, ln in enumerate(body_rows)
            if _line_reuse(ln, mapped.get(bi), old)}


def _annotate_for_save(mode, body_rows, lyric_rows, body_to_lyric,
                       doc, old, annotations):
    """按保存模式生成 body-keyed annotation，并返回共用身份映射。"""
    mapped = _map_new_to_old(body_rows, old)
    reuse = _build_reuse(body_rows, mapped, old)
    if mode == "align":
        old_ann = {bi: old["ann"][old_bi] for bi, old_bi in mapped.items()
                   if old.get("ann", {}).get(old_bi)}
        old_texts = {bi: old["texts"].get(old_bi, "")
                     for bi, old_bi in mapped.items()}
        tokens = {bi: (ln.get("tokens") or [])
                  for bi, ln in enumerate(body_rows)}
        ann = _annotate_lines(body_rows, old_ann, reuse=reuse,
                              old_texts=old_texts, tokens=tokens,
                              old_token_values=old["token_values"])
        return ann, mapped, reuse
    if mode == "annotated":
        return ({bi: annotations[li] for bi, li in body_to_lyric.items()
                 if annotations and li in annotations}, mapped, reuse)
    if mode == "reset":
        return _annotate_lines(body_rows), mapped, reuse
    if mode == "replace":
        return annotations or {}, mapped, reuse
    raise ValueError("未知歌词保存模式：" + str(mode))


def _save_translations(body_rows, body_to_lyric, doc, old, translations):
    """translations 缺省时从显式行/旧文档回退；否则是 body-keyed 快照。"""
    if translations is None:
        if any("trans" in x for x in body_rows):
            translations = {bi: x.get("trans") or ""
                            for bi, x in enumerate(body_rows)}
        else:
            old_body_trans = {}
            for bi, li in old["body_to_lyric"].items():
                text = (doc.get("translations") or {}).get(li, "")
                if str(text or "").strip():
                    old_body_trans[bi] = text
            return DOC.align_translations(body_rows, old["body_rows"], old_body_trans)
    # 显式快照：{} 表示清空全部；只接受非空歌词 body 行。
    return {int(k): str(v or "").strip()
            for k, v in (translations or {}).items()
            if str(v or "").strip() and int(k) in body_to_lyric}


def _resolve_save_ids(body_rows, ann, old, old_map, reuse, line_ids, token_ids):
    """保留未改行的身份；改行只保留能按 tid/span 对上的 token。"""
    out_lids = dict(line_ids or {})
    for bi, ln in enumerate(body_rows):
        if ln.get("lid"):
            out_lids.setdefault(bi, ln["lid"])
    out_tids = dict(token_ids or {})
    for bi, ln in enumerate(body_rows):
        old_bi = old_map.get(bi)
        if bi not in out_lids:
            out_lids[bi] = (old["lids"].get(old_bi) if old_bi is not None else None) or new_line_id()
        seg = (ann or {}).get(bi)
        if not seg or bi in out_tids:
            continue
        old_text = old["texts"].get(old_bi) if old_bi is not None else None
        old_ids = old["tids"].get(old_bi) if old_bi is not None else None
        if bi in reuse and isinstance(old_ids, list) and len(old_ids) == len(seg):
            out_tids[bi] = old_ids
            continue
        fresh = new_token_ids(len(seg))
        used = set()
        pos = 0
        for ti, new_seg in enumerate(seg):
            base = new_seg[0] if new_seg else ""
            start, end = pos, pos + len(base)
            pos = end
            for tok in (ln.get("tokens") or []):
                tid = tok.get("tid")
                if not tid or tid in used:
                    continue
                old_seg = old["token_values"].get(tid)
                if tok.get("start") == start and \
                   tok.get("end") == end and \
                   tok.get("base") == base and \
                   old_seg and old_seg[0] == base:
                    fresh[ti] = tid
                    used.add(tid)
                    break
        out_tids[bi] = fresh
    return out_lids, out_tids


def save_lyrics(item: dict, lines=None, mode="align", annotations=None,
                text=None, expected_version=None, translations=None,
                trans_lang=None, line_ids=None, token_ids=None,
                compact_translations=None) -> dict:
    """唯一的歌词权威写入口：锁内读改写 + 版本校验 + 原子替换。

    mode:
      align      正文没变的行保留旧读音，改字/新行重新注音
      annotated  调用方已经算好 annotations
      replace    换正文（text 或 lines+annotations），旧读音不保留
      reset      正文不变，全部按默认引擎重新注音
    """
    uid = item.get("uid")
    title = item.get("title", "")
    artist = item.get("artist", "")
    saved_ids = []
    with LRC.LOCK, FS.locked(LRC.lock_path()):
        if mode == "replace" and text is not None:
            compact = compact_translations if compact_translations is not None else translations
            res = LRC.import_text(item["file"], text, uid, title, artist,
                                  expected_version=expected_version,
                                  translations=compact,
                                  trans_lang=trans_lang or "zh")
        else:
            doc = LRC.load(item["file"], uid, title, artist)
            if trans_lang is None:
                trans_lang = doc.get("trans_lang") or "zh"
            if mode == "reset" and lines is None:
                lines = doc.get("body_rows") or doc.get("lines") or []
            body_rows = lines or []
            lyric_rows, body_to_lyric = _body_layout(body_rows)
            old = _old_save_layout(doc)
            ann, old_map, reuse = _annotate_for_save(mode, body_rows, lyric_rows,
                                                     body_to_lyric, doc, old, annotations)
            trans = _save_translations(body_rows, body_to_lyric, doc, old,
                                       translations)
            out_lids, out_tids = _resolve_save_ids(body_rows, ann, old, old_map,
                                                   reuse, line_ids, token_ids)
            res = LRC.save(item["file"], body_rows, ann, uid=uid, title=title,
                           artist=artist, expected_version=expected_version,
                           translations=trans, trans_lang=trans_lang,
                           line_ids=out_lids, token_ids=out_tids,
                           metadata=doc.get("metadata"))
            if res.get("ok"):
                saved_ids = _saved_identities(body_rows, ann, out_lids, out_tids)
    if res.get("ok") and saved_ids:
        res["ids"] = saved_ids
    if uid and res.get("ok"):
        try:
            res["library"] = LIB.refresh(uid)
            for _, v in LIB.snapshot():
                if v.get("uid") == uid:
                    v["has_lyric"] = True
                    break
            res["refresh_ok"] = True
        except Exception as e:
            # 写入已经成功；刷新失败不能伪装成"歌词没保存"
            diag.log("library", f"保存后刷新失败 uid={uid}: {e}")
            res["refresh_ok"] = False
            res["refresh_error"] = str(e)
    return res


def _payload_base(item: dict, idx, uid, doc: dict) -> dict:
    """所有分支共用的载荷字段；idx 只做展示，统一为字符串或 None。"""
    return {
        "uid": uid,
        "idx": None if idx is None else str(idx),
        "key": item["key"],
        "title": item["title"],
        "artist": item.get("artist", ""),
        "version": doc.get("version"),
        "duration": LY.audio_duration(item["file"]),
        "audio": f"/audio/{uid}",
        "offset": float(META.get(uid, "offset", 0.0) or 0.0),
    }


def _v2_payload(item: dict, idx, uid, rows_doc: dict) -> dict:
    from .lyric_document import playable_rows
    rows = rows_doc.get("rows") or []
    base = _payload_base(item, idx, uid, {"version": rows_doc.get("version")})
    lines = []
    for row in playable_rows(rows):
        text = row.get("text") or ""
        stored = [[tok.get("base", ""), tok.get("ruby"), tok.get("level")]
                  for tok in (row.get("tokens") or [])]
        fields = ANN_CACHE.line_fields(text, stored or None)
        fields.update({"t": row.get("t"), "text": text, "raw": text,
                       "trans": row.get("trans") or ""})
        lines.append(fields)
    item["has_lyric"] = bool(lines)
    return {**base, "pending": not lines, "lines": lines,
            "nhlrc": True, "disabled": False}


def song_payload(ref, _item=None) -> dict:
    item = _item or LIB.resolve(ref)
    if not item:
        raise KeyError("没有这首歌")
    uid = item.get("uid")
    idx = LIB.idx_for(uid or ref)
    from . import lyric_document as LD
    rows_doc = LD.load_rows(uid)
    if rows_doc.get("ok") and rows_doc.get("model") == 2:
        return _v2_payload(item, idx, uid, rows_doc)
    doc, has_lines = load_lyrics(item)
    base = _payload_base(item, idx, uid, doc)
    if doc.get("disabled"):
        item["has_lyric"] = False
        return {**base, "pending": False, "disabled": True,
                "lines": [], "nhlrc": False}
    if not has_lines:
        item["has_lyric"] = False
        return {**base, "pending": True, "disabled": False, "lines": [],
                "nhlrc": doc.get("kind") == "nhlrc"}
    item["has_lyric"] = True
    lines = doc["lines"]
    stored = doc.get("annotations") or {}
    for li, ln in enumerate(lines):
        if not ln["text"]:
            ln["ruby"], ln["rm"], ln["ky"] = "", "", ""
            continue
        fields = ANN_CACHE.line_fields(ln["text"], stored.get(li))
        ln.update(fields)
        ln["raw"] = ln["text"]
        ln["trans"] = ((doc.get("translations") or {}).get(li) or "")
    return {**base, "pending": False, "lines": lines,
            "nhlrc": doc.get("kind") == "nhlrc", "disabled": False}


def edit_line(uid, li, start, reading):
    """改一处的读音：v2 用 lid/tid，旧文档走原路径。"""
    item = LIB.resolve(uid)
    if not item or not reading:
        return None
    from . import lyric_document as LD
    v2 = LD.load_rows(uid)
    if v2.get("ok") and v2.get("model") == 2:
        rows = v2.get("rows") or []
        items = LD.playable_rows(rows)
        if not (0 <= li < len(items)):
            return None
        row = items[li]
        token = next((t for t in (row.get("tokens") or [])
                      if int(t.get("start", -1)) == int(start)), None)
        if not token:
            return None
        res = LD.edit_reading(uid, row.get("lid"), token.get("tid"), reading,
                              expected_version=v2.get("version"))
        if not res.get("ok"):
            return None
        again = LD.load_rows(uid)
        if not again.get("ok"):
            return None
        target = next((r for r in (again.get("rows") or [])
                       if r.get("kind") == "lyric" and r.get("lid") == row.get("lid")), None)
        if not target:
            return None
        segs = [[t.get("base", ""), t.get("ruby"), t.get("level")]
                for t in (target.get("tokens") or [])]
        fields = ANN_CACHE.line_fields(target.get("text") or "", segs or None)
        return {"line": li, "ruby": fields.get("ruby", ""),
                "rm": fields.get("rm", ""), "ky": fields.get("ky", ""),
                "rmH": fields.get("rmH", ""), "kyH": fields.get("kyH", ""),
                "version": again.get("version")}
    with LRC.LOCK, FS.locked(LRC.lock_path()):
        doc = LRC.load(item["file"], item.get("uid"), item["title"], item.get("artist", ""))
        lines = doc["lines"]
        if not (0 <= li < len(lines)) or not (lines[li].get("text") or "").strip():
            return None
        text = lines[li]["text"]
        clean, _ = strip_paren_ruby(text)
        base = AN.annotate(clean)
        seg = next((x for x in base["lines"][0]["segments"] if x["start"] == start), None)
        if not seg:
            return None
        ann = dict(doc.get("annotations") or {})
        r = annotate_line_with_notes(text, stored=ann.get(li),
                                     extra_start=start, extra_reading=reading)
        ann[li] = segs_of(r)
        body_rows = doc.get("body_rows") or lines
        res = save_lyrics(item, body_rows, "annotated", ann)
        if not res.get("ok"):
            return None
    return {"line": li, "ruby": ruby_html(r), "rm": r.get("romaji", {}).get("text", ""),
            "ky": r.get("keys", {}).get("text", ""),
            "rmH": words_html_of(r, "romaji"), "kyH": words_html_of(r, "keys"),
            "version": res.get("version")}


def rematch(ref, duration):
    """重新匹配：候选只来自网络（网易云），不掺本地缓存。"""
    item = LIB.resolve(ref)
    if not item:
        return {"stem": "", "candidates": []}
    artist, title = LY.split_name(item["stem"])
    duration = float(duration or 0) or LY.audio_duration(item["file"])

    seen, rows = set(), []

    def add(c, src):
        if not c or not c.get("id") or c["id"] in seen:
            return
        if not LY.accept_candidate(c, title, artist, duration):
            return
        delta = (round(c["duration"] - duration, 1)
                 if c.get("duration") and duration else None)
        seen.add(c["id"])
        rows.append({"id": c["id"], "name": c.get("name", ""), "artist": c.get("artist", ""),
                     "duration": c.get("duration") or 0, "delta": delta, "source": src,
                     "score": LY.score_candidate(c, title, artist, duration)})

    for c in LY.search_candidates(title, artist):
        add(c, "netease")

    rows.sort(key=lambda r: -r["score"])
    return {"stem": item["stem"], "candidates": rows[:int(LY.CFG["manual_limit"])]}


def pick(uid, song_id) -> dict:
    """用户选定候选：用网络歌词替换当前歌词（重写 data/lyrics，读音全部重来）。"""
    item = LIB.resolve(uid)
    if not item or not song_id:
        return {"ok": False, "error": "缺少歌曲或候选 id"}
    artist, title = LY.split_name(item["stem"])
    hit = LY.fetch_lyrics_by_id(song_id)
    lrc = hit.get("lrc") or ""
    if not LY.valid_lrc(lrc):
        return {"ok": False, "error": "这个候选没有带时间轴的可用歌词"}
    trans = DOC.translations_from_lrc(hit.get("tlyric") or "", DOC.parse(lrc))
    # 重写当前歌曲的 nhlrc 正文（备份旧文件），旧读音不保留
    try:
        res = save_lyrics(item, mode="replace", text=lrc,
                          compact_translations=trans)
    except Exception as e:
        return {"ok": False, "error": "写歌词失败：" + str(e)}
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error") or "写歌词失败"}
    d = song_payload(None, item)   # 用刚保存的同一份条目回读，不再回查 idx
    return {"ok": True, "uid": item.get("uid"), "idx": d.get("idx"),
            "lines": len(d.get("lines") or [])}

def lazy_match(item: dict) -> None:
    """按需抓歌词；明确禁用歌词的歌不联网。"""
    if LRC.load(item["file"], item.get("uid"), item.get("title"), item.get("artist", "")).get("disabled"):
        return
    artist, title = LY.split_name(item["stem"])
    LY.get_lrc(title, artist, duration=LY.audio_duration(item["file"]), force=True)
    LIB.refresh(item.get("uid"))


# ── HTTP 用得着的两个封装 ─────────────────────────────
def edit_line_action(req) -> dict:
    """改一处读音（HTTP 用）：改完立即写盘；失败返回 {"error"}。"""
    line = int(req.get("line", -1))
    start = int(req.get("start", -1))
    reading = str(req.get("reading") or "")
    r = edit_line(req.get("uid"), line, start, reading)
    if not r:
        return {"error": "读音保存失败"}
    return r
