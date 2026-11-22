# nhlrc 格式

> 本文是 `.nhlrc` 的格式规范。总体分层和边界见 [架构文档](../architecture.md)。

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

`.nhlrc` 是权威歌词文档。歌词缓存、tlyric、注音缓存都不能替代它。

## 1. 文件位置与命名

```text
data/lyrics/<title> - <artist>.<uid>.nhlrc
data/lyrics/bak/<name>.nhlrc.bak
data/lyrics/.lock
```

```text
开发时 data = 项目/data；
打包后 data = ~/Library/Application Support/nihonco uta/data。
```

规则：

```text
uid = 音频指纹，是歌曲身份
文件名 = 可读标题/歌手 + uid，只负责可读
标题/歌手会做非法字符替换、空白折叠、最多 120 字节
查找已有文件时按 uid 后缀匹配，不依赖文件名前缀
```

```text
不用 idx 命名。
不把 nhlrc 写进音乐目录。
```

## 2. 整体结构

```text
[LRC 正文]

#NHLRC 1
{ JSON 尾部 }
```

```text
正文和尾部之间有空行。
#NHLRC 1 是标记行。
尾部从下一行开始，必须是一个 JSON object。
```

关键规则：

```text
没有 #NHLRC 标记
  → 当成纯 LRC 正文

有标记但尾部 JSON 解析失败
  → 尾部整体忽略，正文仍然可用

有标记但尾部不是 object
  → 同上
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

标准形式：

```lrc
[mm:ss.xx]文本
```

也接受：

```lrc
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

保存时保留元数据及其大致位置。

### 3.3 无时间戳行

```text
没有时间戳的非空行可以存在。
它是草稿行，t = null。
```

```text
普通播放只使用有时间戳的行。
LRC 编辑器保留草稿行。
```

### 3.4 网易云 JSON 行

正文解析兼容这一种输入：

```json
{"t":1234,"c":[{"tx":"あの日"}]}
```

```text
t 是毫秒。
写入 nhlrc 时会渲染成普通 LRC 时间戳行。
```

## 4. 尾部字段

```json
{
  "v": 1,
  "gen": "nihonco 0.1",
  "body": "a1b2c3d4",
  "lines": [],
  "trans_lang": "zh",
  "trans": [],
  "disabled": false
}
```

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `v` | int | 是 | 格式版本，当前 1 |
| `gen` | str | 否 | 生成器标记 |
| `body` | str | 否 | 正文 hash，8 位 |
| `lines` | array | 否 | 读音数组 |
| `trans_lang` | str | 否 | 翻译语言，默认 `zh` |
| `trans` | array | 否 | 翻译数组 |
| `disabled` | bool | 否 | 用户禁用歌词 |

```text
未知字段忽略。
缺失字段表示没有该能力。
```

## 5. 读音 `lines`

```json
{"i": 0, "h": "1234abcd", "seg": [["君", "きみ", "A"], ["の", "の", null]]}
```

| 字段 | 含义 |
|---|---|
| `i` | 正文行号，从 0 开始 |
| `h` | 该行正文文本的 8 位 hash |
| `seg` | `[base, ruby, level]` 序列 |

```text
lines 是稀疏数组。
没有读音的行不出现。
```

`seg` 也接受对象写法：

```json
{"b": "君", "r": "きみ", "lv": "A"}
```

但写入时统一成数组。

校验：

```text
i 越界           → 忽略该条
seg 为空         → 忽略该条
seg 拼接 ≠ 行文本 → 忽略该条
h 不匹配且严格模式 → 忽略该条
```

## 6. 翻译 `trans`

```json
{"i": 0, "h": "1234abcd", "text": "呼唤你的名字"}
```

| 字段 | 含义 |
|---|---|
| `i` | 正文行号 |
| `h` | 该行正文文本的 8 位 hash |
| `text` | 译文 |

```text
trans 是稀疏数组。
没有翻译的行不出现。
翻译不存时间戳。
翻译不进入正文。
```

```text
trans_lang 当前默认 "zh"。
```

### 6.1 对齐规则

```text
只改时间戳
  → 正文 text 不变
  → h 不变
  → trans 保留

改正文文本
  → h 变化
  → 该条 trans 失效

插入/删除/移动行
  → 按 i + h 重新对齐
```

## 7. hash

```text
body = sha1(渲染后的正文).hexdigest()[:8]
h    = sha1(单行 text).hexdigest()[:8]
```

```text
body 一致
  → 可以跳过逐行 h 校验（fast path）

body 不一致
  → 退回逐行 h 校验

h 是变更检测，不是安全校验。
```

## 8. 读取规则

```text
有 .nhlrc
  → 只读 .nhlrc
  → disabled 直接返回空歌词
  → 正文 + lines + trans

没有 .nhlrc
  → 读歌词缓存
  → tlyric 只作为显示来源
```

```text
有 .nhlrc 但没有 trans
  → 不回填缓存翻译
```

读取时：

```text
正文：按文件顺序解析
lines：annotations_for 校验
trans：translations_for 校验
disabled：直接短路
```

## 9. 写入规则

```text
保存
  → 版本校验
  → 首次覆盖前备份
  → 锁内读改写
  → 原子替换

删除
  → 写 disabled 文档
  → 保留旧备份

恢复
  → 从备份恢复
  → 重新启用

导入
  → 统一校验
  → 直接写权威 nhlrc
```

```text
保存时必须保留没有参与本次编辑的 lines / trans。
只有主动替换整份歌词或删除歌词才清空它们。
```

## 10. disabled

```text
#NHLRC 1
{
 "v": 1,
 "gen": "nihonco 0.1",
 "disabled": true
}
```

```text
disabled 是持久化用户选择，不是缓存。
disabled 文档没有正文。
disabled 不会被再次备份成可恢复歌词。
```

## 11. 备份

```text
首次覆盖前生成 bak
disabled 不作为 bak
恢复只接受非 disabled 的备份
```

```text
bak 是“最早那次保存前”的版本，不是每次保存都覆盖。
```

## 12. 导入校验

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
  → 它是已整理文档

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

## 13. 示例

### 只有正文

```lrc
[00:01.00]君の名前
[00:02.00]届くまで
```

### 正文 + 读音

```lrc
[00:01.00]君の名前

#NHLRC 1
{
 "v": 1,
 "gen": "nihonco 0.1",
 "body": "a1b2c3d4",
 "lines": [
  {"i": 0, "h": "1234abcd", "seg": [["君","きみ","A"],["の","の",null],["名前","なまえ","A"]]}
 ]
}
```

### 正文 + 读音 + 翻译

```lrc
[00:01.00]君の名前

#NHLRC 1
{
 "v": 1,
 "gen": "nihonco 0.1",
 "body": "a1b2c3d4",
 "lines": [
  {"i": 0, "h": "1234abcd", "seg": [["君","きみ","A"]]}
 ],
 "trans_lang": "zh",
 "trans": [
  {"i": 0, "h": "1234abcd", "text": "你的名字"}
 ]
}
```

### disabled

```lrc
#NHLRC 1
{
 "v": 1,
 "gen": "nihonco 0.1",
 "disabled": true
}
```

## 14. 禁止事项

```text
× 把翻译拼进正文
× 用 idx 做身份
× 手改 h 而不改正文
× 把 tlyric 原样当 nhlrc 尾部
× 在 disabled 文档里保留正文
× 把 body hash 当安全校验
× 导入空文件或乱码文件
```

## 15. 版本与兼容

```text
v = 1
新增可选字段不升级 v
不设计旧数据迁移
不做双读
不做回填
```

```text
旧文件没有 trans → 就是没有翻译
旧文件没有 disabled → 正常歌词
```

## 16. 相关专题

```text
tlyric 来源/时间配对 → lyrics-matching.md
翻译列编辑 → lrc-editor.md
播放器状态机 → player-state.md
```
