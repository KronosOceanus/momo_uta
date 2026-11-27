# Meta 行统一判定

> 状态：已实现（2026-11-27）。
> 目标：让后端、编辑器、播放层共用同一套 meta 行判定，避免同一种行在不同层得到不同结果。

## 1. 背景

现在 meta 行有三套判断。

### 1.1 后端

`src/momo_player/core/lrc_doc.py`：

```python
METADATA = re.compile(
    r"(?:\[(?:ar|al|ti|au|by|offset|length|re|ve|la|id|tool):[^\]\r\n]*\][ \t]*)+",
    re.IGNORECASE,
)
```

只认这些 LRC 标签：

```text
[ar:]  [al:]  [ti:]  [au:]  [by:]  [offset:]
[length:]  [re:]  [ve:]  [la:]  [id:]  [tool:]
```

命中后：

```python
{"kind": "metadata", "text": raw, "t": None}
```

`playable()` 只取：

```python
kind == "lyric" and t is not None
```

所以真正的 metadata 行不会进入播放层。

### 1.2 编辑器

`20-editor.js`：

```js
function rowKind(text) {
  const t = (text || '').trim();
  if (!t) return 'blank';
  if (/^\[(ar|al|ti|au|by|offset|length|re|ve|la|id|tool):/i.test(t))
    return 'metadata';
  return 'lyric';
}
```

只按标签前缀判断，不认正文里的制作信息。

### 1.3 播放层

`30-playback.js`：

```js
const META_RE = /^(作词|作曲|编曲|制作|演唱|歌\s*[:：]|Lyrics|Composer|Arranger|Producer)/;

function isMetaLine(l) {
  return !l || l.meta || META_RE.test((l.text || '').trim());
}
```

这是文本前缀兜底。

## 2. 当前问题

### 2.1 三套规则

```text
后端：LRC 标签 fullmatch
编辑器：LRC 标签前缀
播放层：制作信息文本前缀
```

同一个行可能：

```text
编辑器认为是歌词
播放层认为是 meta
后端认为是普通 lyric
```

### 2.2 日文常用写法没覆盖

播放层只匹配：

```text
作词  作曲  编曲
```

漏了：

```text
作詞  編曲  訳詞
```

所以：

```text
[00:00.00]作詞: 星野源
```

会被当成普通歌词高亮。

### 2.3 没有统一 kind

后端 payload 的播放行不生产 `meta` 字段。  
播放层的 `l.meta` 主要存在于测试构造的数据里，线上主要靠文本正则。

### 2.4 时间戳可能丢失

如果有时是：

```text
[00:00.00]作詞: 星野源
```

一旦被标成 metadata，当前导出逻辑可能只写正文，丢掉 `[00:00.00]`。

## 3. 统一目标

定义唯一语义：

```text
meta 行 = 制作信息行
```

只要命中，就写入：

```python
kind = "metadata"
```

所有层都以 `kind` 为准。

### 3.1 算 metadata 的行

```text
[ar:Artist]
[al:Album]
[ti:Title]
[offset:100]

[00:00.00]作詞: 星野源
[00:00.00]作词 : 星野源
[00:00.00]作曲: 星野源
[00:00.00]編曲: 星野源
[00:00.00]訳詞: 某人
[00:00.00]制作: 某人
[00:00.00]Lyrics: 某人
[00:00.00]Composer: 某人
[00:00.00]Arranger: 某人
[00:00.00]Producer: 某人
[00:00.00]Lyrics by: 某人
[00:00.00]Produced by: 某人
[00:00.00]Composed by: 某人
```

### 3.2 不算 metadata 的行

```text
[00:10.00]作詞の歌を歌う
[00:10.00]作曲家的故事
[00:10.00]普通歌词
```

关键区别：

```text
制作信息关键词 + 冒号
```

不是只看关键词开头。

### 3.3 空行

```text
空行 → kind = "blank"
```

不受影响。

## 4. 统一判定函数

建议放在：

```text
src/momo_player/core/lrc_doc.py
```

新增：

```python
META_TAGS = ...
META_CREDIT = re.compile(
    r"^(?:作詞|作词|作曲|編曲|编曲|訳詞|訳词|制作|製作|演唱|歌"
    r"|Lyrics|Composer|Arranger|Producer)\s*[:：]",
    re.IGNORECASE,
)

def is_metadata_text(text: str) -> bool:
    ...
```

### 4.1 判定顺序

```text
1. 去掉首尾空白
2. 整行匹配 metadata 标签 → metadata
3. 去掉行首连续的 metadata 标签
4. 剩下正文匹配 META_CREDIT → metadata
5. 其他 → 非 metadata
```

### 4.2 多标签

```text
[ar:A][ti:B]
```

应判为 metadata。

### 4.3 标签 + 正文

```text
[ar:A]作詞: B
```

也建议判为 metadata，  
但这是兼容性边缘情况，不作为主要格式。

## 5. 解析后的行模型

### 5.1 标签行

```text
[ar:Artist]
→ kind=metadata, t=None
```

### 5.2 带时间制作信息

```text
[00:00.00]作詞: 星野源
→ kind=metadata, t=0.0
```

保留 `t`，  
但 metadata 不进入 `playable()`。

### 5.3 普通歌词

```text
[00:10.00]あの日見渡した渚を
→ kind=lyric, t=10.0
```

### 5.4 无时间制作信息

```text
作詞: 星野源
→ kind=metadata, t=None
```

## 6. 播放层

`playable()` 已经是：

```python
kind == "lyric" and t is not None
```

统一后不需要再让播放层猜。

`isMetaLine()` 建议改成：

```js
function isMetaLine(l) {
  return !l
    || l.kind === 'metadata'
    || l.meta
    || META_RE.test((l.text || '').trim());
}
```

规则：

```text
kind 是主判据
l.meta 和 META_RE 只做旧数据兜底
```

最终播放层 `LINES` 里不应该出现 metadata，  
所以文本正则只是兼容旧缓存/旧 payload。

## 7. 编辑器

`rowKind()` 使用同一套规则：

```js
function rowKind(text) {
  const t = (text || '').trim();
  if (!t) return 'blank';
  if (META_TAG_RE.test(t) || META_CREDIT_RE.test(t))
    return 'metadata';
  return 'lyric';
}
```

这样用户手动输入：

```text
作詞: X
```

会立即被当成 metadata，  
不会生成读音、不会进入播放导航。

## 8. 导出

### 8.1 后端

`core/lyric_rows.py` 的 `body_text()` 对 metadata 行：

```text
有 t → [mm:ss.xx] + 原文
无 t → 原文
```

不能因为 `kind=metadata` 就无条件丢掉时间戳。

### 8.2 前端

`20-editor.js` 的 `lrcText()` 同样处理：

```js
if ((r.kind || rowKind(r.text)) === 'metadata') {
  const stamp = lrcFmt(r.t);
  return `${stamp ? `[${stamp}]` : ''}${r.text || ''}`;
}
```

否则：

```text
[00:00.00]作詞: X
```

保存一次就会变成：

```text
作詞: X
```

## 9. 要改的文件

```text
src/momo_player/core/lrc_doc.py
  统一 META_TAGS / META_CREDIT / is_metadata_text

src/momo_player/core/lyric_rows.py
  _row_from_line 使用统一判定
  body_text 保留 metadata 时间戳

src/momo_player/core/lrc_files.py
  body → rows 时使用统一判定

src/momo_player/static/20-editor.js
  rowKind 同步规则
  lrcText 保留 metadata 时间戳
  lrcPayload 发送 kind

src/momo_player/static/30-playback.js
  isMetaLine 优先看 kind

README.md
  meta 行规则说明
```

## 10. 迁移

不需要改文件格式。

`.nhlrc` 正文仍然是原文：

```text
[00:00.00]作詞: 星野源
```

下次解析：

```text
is_metadata_text()
→ kind=metadata
```

旧数据自动获得新分类。

不需要批量迁移。

## 11. 测试

### 后端

```text
[ar:Artist]                  → metadata
[ar:A][ti:B]                → metadata
[00:00.00]作詞: X            → metadata, t=0
[00:00.00]作词 : X           → metadata
[00:00.00]編曲: X            → metadata
[00:00.00]Lyrics: X          → metadata
[00:10.00]作詞の歌を歌う      → lyric
[00:10.00]普通歌词            → lyric
```

### 播放

```text
metadata 不进入 playable
metadata 不进入上一句 / 下一句
metadata 不参与当前行高亮
```

### 导出

```text
[00:00.00]作詞: X
→ 保存后仍保留 [00:00.00]
```

### 编辑器

```text
输入 作詞: X → kind=metadata
输入 作詞の歌 → kind=lyric
```

## 12. 风险

```text
把真实歌词误判成 metadata
→ 只匹配“关键词 + 冒号”，不裸匹配关键词
→ 保留正常歌词测试

时间戳丢失
→ 前后端导出都要覆盖

旧缓存 payload 没有 kind
→ isMetaLine 保留 text 正则兜底
```

## 13. 实施顺序

```text
1. 后端统一 is_metadata_text
2. 行解析写入 kind
3. playable / 导出
4. 编辑器 rowKind
5. 播放层 isMetaLine
6. 测试与文档
```

## 14. 结论

补充实现：

```text
[ar:X]hello 这类“标签 + 普通正文”统一按标签判为 metadata
metadata 旧投影保留 t，不再丢 [mm:ss.xx]
Lyrics by / Produced by / Composed by 已纳入
前后端用同一组样例做行为一致性测试
```

统一后只有一个权威判定：

```text
kind == "metadata"
```

三层职责：

```text
后端：分类并持久化
编辑器：显示、编辑、保存
播放层：只消费 kind
```

文本正则只作为旧数据兜底，  
不再承担主判据。

## 15. 歌词页显示

metadata 仍然：

```text
不进入 playable
不进入导航
不参与高亮
```

但 `/api/song` 额外返回：

```json
"credits": [{"text": "作詞: X", "t": 0.0}]
```

歌词页在顶部渲染为静态 `.lmeta` 行，  
LRC 编辑器仍然从 `rows` 中正常显示和编辑。

## 16. 实现结果

已落地：

```text
lrc_doc.is_metadata_text       统一判定函数
lrc_doc._parse_rows            带时间制作信息不再进入 compact lines
lyric_rows._row_from_line       标签行 / 制作信息行写入 kind=metadata
lyric_rows.body_text            metadata 行保留时间戳
lrc_files._rows_from_body       旧 body 入口同样分类
20-editor.rowKind               前端同步制作信息判定
20-editor.lrcText               metadata 行保留时间戳
30-playback.isMetaLine          优先看 kind，文本正则仅旧数据兜底
service/song.credits            歌词页顶部静态制作信息
10-app.creditHtml               不进入 LINES，不影响索引
```

新增覆盖：

```text
[00:00]作詞/作词/編曲/Lyrics → metadata
作詞の歌 → lyric
metadata 保留 [00:00.00]
metadata 不进入 playable
歌词页顶部显示 credits
LRC 编辑器可编辑 metadata
编辑器 rowKind 与 lrcText
```

验证：

```text
449 Python
110 前端
pyflakes 通过
架构检查通过
前端检查通过
```
