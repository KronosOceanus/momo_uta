"""测试专用 V1 夹具生成器；生产代码不再包含 V1 写入器。"""
import json

from nihonco_player.core import lrc_doc as D


def render_body(lines, metadata=None):
    return D.render(lines, metadata)


def render_nhlrc(lines, metadata=None, annotations=None, translations=None,
                 trans_lang="zh", line_ids=None, token_ids=None,
                 annotation_index=None):
    body = D.render(lines, metadata)
    entries = []
    seen_l, seen_t = set(), set()
    for i, seg in sorted((annotations or {}).items()):
        if not (0 <= i < len(lines) and seg):
            continue
        tail_i = (annotation_index or {}).get(i, i)
        ent = {"i": tail_i, "h": D._hash8(lines[i].get("text") or ""), "seg": seg}
        lid = (line_ids or {}).get(i)
        if lid is not None:
            if not D._valid_id(lid, "l") or lid in seen_l:
                lid = D._unique_id("l", seen_l)
            ent["lid"] = lid
            seen_l.add(lid)
        tids = (token_ids or {}).get(i)
        if tids is not None:
            if not isinstance(tids, list) or len(tids) != len(seg):
                tids = [None] * len(seg)
            final = []
            for tid in tids:
                if not D._valid_id(tid, "t") or tid in seen_t:
                    tid = D._unique_id("t", seen_t)
                final.append(tid)
                seen_t.add(tid)
            ent["tid"] = final
        entries.append(ent)
    trans = []
    for i, text in sorted((translations or {}).items()):
        text = str(text or "").strip()
        if text and 0 <= i < len(lines):
            trans.append({"i": (annotation_index or {}).get(i, i),
                          "h": D._hash8(lines[i].get("text") or ""), "text": text})
    if not entries and not trans:
        return body
    rows = []
    for ent in entries:
        parts = [f'"i": {ent["i"]}', f'"h": "{ent["h"]}"']
        if ent.get("lid"):
            parts.append(f'"lid": {json.dumps(ent["lid"], ensure_ascii=False)}')
        parts.append(f'"seg": {json.dumps(ent["seg"], ensure_ascii=False, separators=(",", ":"))}')
        if ent.get("tid"):
            parts.append(f'"tid": {json.dumps(ent["tid"], ensure_ascii=False, separators=(",", ":"))}')
        rows.append("  {" + ", ".join(parts) + "}")
    tail = ('{\n'
            f' "v": {D.NHLRC_VERSION},\n'
            f' "gen": "{D.GEN}",\n'
            f' "body": "{D._hash8(body)}",\n'
            ' "lines": [\n' + ",\n".join(rows) + '\n ]')
    if trans:
        trows = [f'  {{"i": {e["i"]}, "h": "{e["h"]}", "text": {json.dumps(e["text"], ensure_ascii=False)}}}'
                 for e in trans]
        tail += (f',\n "trans_lang": {json.dumps(str(trans_lang or "zh"), ensure_ascii=False)},\n'
                 ' "trans": [\n' + ",\n".join(trows) + '\n ]')
    return body + "\n" + D.NHLRC_MARK + f" {D.NHLRC_VERSION}\n" + tail + '\n}'
