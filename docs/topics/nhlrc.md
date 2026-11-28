# nhlrc 格式

> 本文是 `.nhlrc` 的格式规范。总体分层和边界见 [架构文档](../architecture.md)。
> 用户概念只有一个 **nhlrc**。文件内部的 `"v": 2` 只是格式标记，
> 不再区分 V1 / V2；旧 V1 文件不支持。

## 0. 一句话

```text
.nhlrc = 权威歌词正文
        + 可选读音尾部
        + 可选翻译尾部
        + 可选 disabled 状态
```

它不是普通 `.lrc`：

```text
普通 .lrc：只有歌词正文
.nhlrc：正文 + 可选 JSON 尾部
```

## 1. 文件位置与命名

```text
data/lyrics/<title> - <artist>.<uid>.nhlrc
data/lyrics/bak/<name>.nhlrc.bak
data/lyrics/.lock
```

```text
开发时 data = 项目/data；
打包后 data = ~/Library/Application Support/momo uta/data。
```

规则：

```text
uid = 音频指纹，是歌曲身份
文件名 = 可读标题/歌手 + uid
标题/歌手做非法字符替换、空白折叠、最多 120 字节
查找已有文件时按 uid 后缀匹配
```

```text
不用 idx 命名。
不把 nhlrc 写进音乐目录。
```

## 2. 整体结构

```text
[LRC 正文]

#NHLRC 2
{ JSON 尾部 }
```

```text
正文和尾部之间有空行。
#NHLRC 2 是标记行。
尾部从下一行开始，必须是一个 JSON object。
```

```text
没有 #NHLRC 标记
  → 当成纯 LRC 正文，读取时在内存转成 nhlrc rows

有标记但版本不是 2
  → 拒绝（不读取 V1）

有标记但尾部 JSON 解析失败
  → 尾部整体忽略，正文仍然可用
```

## 3. 正文格式

正文支持：

```lrc
[ar:歌手]
[ti:曲名]
[00:12.34]君の名前を呼ぶよ
[00:16.20]届くまで
```

### 3.1 时间戳行

```lrc
[mm:ss.xx]文本
[mm:ss.xxx]文本
```

```text
时间只用于排序/定位/显示。
正文顺序不被自动重排；编辑器保留文件顺序。
```

### 3.2 元数据行

```text
[ar:...]
[ti:...]
[al:...]
[by:...]
[offset:...]
```

```text
metadata 是 rows 中的 kind=metadata 行。
保存时保留行位置，不再使用 compact before 映射。
```

### 3.3 无时间戳行

```text
没有时间戳的非空行可以存在。
它是草稿行，t = null，kind=lyric。
```

```text
普通播放只使用 t != null 的 lyric 行。
LRC 编辑器保留草稿行。
```

### 3.4 空行

正文允许空行，保存时保留：

```text
kind=blank
text=""
t 可以是 null，也可以保留时间戳
```

```text
空行不进入播放视图。
空行不写入 lines / trans 尾部。
空行仍然出现在 LRC 编辑器。
```

### 3.5 尾部空格

```text
正文文本原样保留，包括行尾空格。
h 按保留后的 text 计算。
```

```text
token 只覆盖实际字符。
token 覆盖完字符后允许剩余尾部空白。
```

### 3.6 网易云 JSON 行

正文解析兼容：

```json
{"t":1234,"c":[{"tx":"あの日"}]}
```

```text
t 是毫秒。
写入 nhlrc 时渲染成普通 LRC 时间戳行。
```

## 4. 尾部字段

```json
{
  "v": 2,
  "gen": "momo 0.1",
  "body": "a1b2c3d4",
  "lines": [],
  "trans_lang": "zh",
  "trans": [],
  "disabled": false
}
```

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `v` | int | 是 | 格式版本，写入固定 2 |
| `gen` | str | 否 | 生成器标记 |
| `body` | str | 否 | 正文 hash，8 位 |
| `lines` | array | 否 | 读音数组 |
| `trans_lang` | str | 否 | 翻译语言，缺省 `zh` |
| `trans` | array | 否 | 翻译数组 |
| `disabled` | bool | 否 | 用户禁用歌词 |

```text
未知字段忽略。
缺失字段表示没有该能力。
```

## 5. 行身份与 `i`

```text
i = rows 中的 body 行号
```

它包含：

```text
metadata
blank
lyric
```

`i` 只负责把尾部条目锚回具体正文行：

```text
lid = 真正的行身份
tid = token 身份
h   = 文本校验
```

```text
i 不是身份。
行移动/插入/删除由 lid 保持身份。
```

## 6. 读音 `lines`

```json
{
  "i": 1,
  "lid": "l_8f3a2c1d",
  "h": "1234abcd",
  "seg": [["君", "きみ", "A"], ["の", "の", null]],
  "tid": ["t_91ab77cd", "t_77cd42ef"]
}
```

| 字段 | 含义 |
|---|---|
| `i` | rows 中的 body 行号 |
| `lid` | 行身份 |
| `h` | 该行正文文本的 8 位 hash |
| `seg` | `[base, ruby, level]` 序列 |
| `tid` | 与 seg 一一对应的 token 身份 |

```text
每一条 lyric 行都应写 lines 条目。
即使没有读音/token，也写：
  "seg": [], "tid": []
这样 lid 和 trans 仍然有锚点。
```

```text
lines 是稀疏数组。
blank / metadata 不出现。
```

`seg` 也接受对象写法：

```json
{"b": "君", "r": "きみ", "lv": "A"}
```

但写入时统一成数组。

校验：

```text
i 越界             → 忽略该条
目标不是 lyric     → 忽略该条
seg 拼接 ≠ 行文本  → 忽略该条
h 不匹配           → 忽略该条
lid 重复           → 忽略后出现的条目
tid 数量 ≠ seg 数量 → 该行 token 丢弃
```

```text
token 分段覆盖文本后，允许尾部空白。
```

## 7. 翻译 `trans`

```json
{"i": 1, "lid": "l_8f3a2c1d", "h": "1234abcd", "text": "呼唤你的名字"}
```

| 字段 | 含义 |
|---|---|
| `i` | rows 中的 body 行号 |
| `lid` | 该行身份 |
| `h` | 该行正文 hash |
| `text` | 译文 |

```text
trans 是稀疏数组。
blank / metadata 不出现。
翻译不存时间戳，不进入正文。
```

```text
trans_lang 缺省 "zh"。
保存时如果省略 trans_lang，沿用旧文档值。
```

### 7.1 对齐规则

```text
只改时间戳
  → text 不变
  → h 不变
  → trans 保留

改正文文本
  → h 变化
  → 该条 trans 失效

插入/删除/移动行
  → 按 lid 对齐

清空为 blank
  → trans 清空
```

## 8. hash

```text
body = sha1(渲染后的正文).hexdigest()[:8]
h    = sha1(单行 text).hexdigest()[:8]
```

```text
h 按保留尾部空格的 text 计算。
h 是变更检测，不是安全校验。
```

## 9. 读取规则

```text
有 .nhlrc
  → 只读 .nhlrc
  → rows

有旧版 .nhlrc
  → 不支持的 nhlrc 版本
  → 不读取

没有 .nhlrc
  → 读歌词缓存
  → 缓存只作为显示来源
```

```text
有 .nhlrc 但没有 trans
  → 不回填缓存翻译
```

```text
disabled nhlrc
  → 直接短路成 disabled
  → 不解析正文
```

## 10. 写入规则

```text
保存
  → 版本校验
  → 首次覆盖前备份
  → 锁内读改写
  → 原子替换
  → 写 nhlrc

删除
  → 写 nhlrc disabled
  → 保留旧备份

恢复
  → 只恢复 nhlrc 备份

导入
  → 统一校验
  → 普通 LRC 转 nhlrc
  → 旧版 nhlrc 拒绝
```

```text
保存时必须保留没有参与本次编辑的 rows / trans。
只有主动替换整份歌词或删除歌词才清空它们。
```

```text
核心写入入口：
  save_rows(rows)
  → 新功能、新字段唯一入口

旧兼容入口：
  LRC.save(lines, ...)
  → 只做旧 body 参数到 rows 的适配
  → 不再新增保存语义
```

## 11. disabled

```text
#NHLRC 2
{
 "v": 2,
 "gen": "momo 0.1",
 "disabled": true
}
```

```text
disabled 是持久化用户选择，不是缓存。
disabled 文档没有正文。
disabled 不会被再次备份成可恢复歌词。
```

## 12. 备份

```text
首次覆盖前生成 bak
disabled 不作为 bak
恢复只接受非 disabled 的备份
V1 备份拒绝恢复
```

```text
bak 是“最早那次保存前”的版本，不是每次保存都覆盖。
```

## 13. 导入校验

所有导入入口统一走：

```python
LRC.valid_import(text)
```

规则：

```text
空文件
  → 拒绝

包含 UTF-8 替换字符
  → 拒绝

普通 .lrc
  → 至少有 min_content_lines 行有效时间轴
  → 元数据行不算

带 lines / trans 尾部的 .nhlrc
  → 允许少于普通 LRC 行数

disabled .nhlrc
  → 允许
  → 导入后仍保持 disabled
```

```text
校验失败：
  不备份
  不覆盖
  不写 nhlrc
```

## 14. 示例

### 只有正文

```lrc
[00:01.00]君の名前
[00:02.00]届くまで
```

### 正文 + 读音

```lrc
[00:01.00]君の名前

#NHLRC 2
{
 "v": 2,
 "gen": "momo 0.1",
 "body": "a1b2c3d4",
 "lines": [
  {
   "i": 0,
   "lid": "l_8f3a2c1d",
   "h": "1234abcd",
   "seg": [["君","きみ","A"],["の","の",null],["名前","なまえ","A"]],
   "tid": ["t_a","t_b","t_c"]
  }
 ]
}
```

### 正文 + 读音 + 翻译

```lrc
[00:01.00]君の名前

#NHLRC 2
{
 "v": 2,
 "gen": "momo 0.1",
 "body": "a1b2c3d4",
 "lines": [
  {
   "i": 0,
   "lid": "l_8f3a2c1d",
   "h": "1234abcd",
   "seg": [["君","きみ","A"]],
   "tid": ["t_a"]
  }
 ],
 "trans_lang": "zh",
 "trans": [
  {"i": 0, "lid": "l_8f3a2c1d", "h": "1234abcd", "text": "你的名字"}
 ]
}
```

### disabled

```lrc
#NHLRC 2
{
 "v": 2,
 "gen": "momo 0.1",
 "disabled": true
}
```

## 15. 禁止事项

```text
× 把翻译拼进正文
× 用 idx 做身份
× 手改 h 而不改正文
× 把 tlyric 原样当 nhlrc 尾部
× 在 disabled 文档里保留正文
× 把 body hash 当安全校验
× 导入空文件或乱码文件
× 新写入 V1
```

## 16. 版本与兼容

```text
写入固定 v = 2
旧版不再支持
读取、导入、恢复都拒绝旧版
普通 LRC 仍可导入并转成 nhlrc
```

```text
旧文件没有 trans → 就是没有翻译
旧文件没有 disabled → 正常歌词
```

## 17. 相关专题

```text
tlyric 来源/时间配对 → lyrics-matching.md
翻译列编辑 → lrc-editor.md
行/token ID → nhlrc-token-ids.md
单一行模型 → ../歌词数据模型.md
```
