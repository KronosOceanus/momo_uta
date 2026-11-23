# nhlrc 行 ID 与 token ID

> 格式基础见 [nhlrc](nhlrc.md)，单一行模型见 [歌词数据模型](../歌词数据模型.md)。
> 当前写入版本：v2。

## 0. 一句话

```text
lid = 行身份
tid = token 身份
i   = body 行号，仅用于锚定尾部
h   = 正文 hash，仅用于校验
```

```text
身份不由行号、hash、文本或位置推断。
```

## 1. 数据结构

```json
{
  "i": 1,
  "lid": "l_8f3a2c1d",
  "h": "a1b2c3d4",
  "seg": [
    ["君", "きみ", "A"],
    ["の", null, "K"],
    ["名前", "なまえ", "A"]
  ],
  "tid": ["t_91ab77cd", "t_77cd42ef", "t_42ef91ab"]
}
```

```text
i     rows 中的 body 行号，包含 blank / metadata
lid   行身份
h     正文 hash
seg   [base, ruby, level]
tid   与 seg 一一对应的 token 身份
```

```text
lid 在整首歌内唯一
tid 在整首歌内唯一
```

## 2. 身份规则

### 2.1 行

```text
改文字        → lid 不变
改时间        → lid 不变
改翻译        → lid 不变
上下移动      → lid 不变
插入/删除其他行 → lid 不变
```

```text
lyric → blank
  → lid 清除
  → tokens 清空
  → trans 清空

blank → lyric
  → 新 lid
  → 新 tokens
  → trans 为空
```

### 2.2 token

```text
完整 token 在行内移动
  → tid 保留

token 被拆开
  → 被拆的 token 丢弃
  → 两侧重新注音

token 文本未变
  → tid 和手工读音保留

token 文本变化
  → 该 token 丢弃，重新注音
```

### 2.3 重复 token

```text
两个相同 base 的 token
  → 各自有独立 tid
  → 读音可以不同
```

```text
不能按 base 合并。
不能按出现次序猜。
```

## 3. UTF-16 span

token span 使用：

```text
UTF-16 code units
```

```text
前端 selectionStart / JS slice 是 UTF-16
后端按 UTF-16 → Python code point 转换后切片
```

例子：

```text
"𠮷君"
  𠮷 = [0, 2)
  君 = [2, 3)
```

```text
Python 的 len() 不能直接当 token span。
```

## 4. 前端模型

```js
{
  id,        // 编辑器行身份
  kind,      // lyric / blank / metadata
  text,
  t,         // 可为 null
  lid,
  tokens: [
    {tid, start, end, base, ruby, level}
  ],
  trans
}
```

```text
行位置只用于显示。
更新行时按 lid。
更新 token 时按 tid。
```

## 5. 文本编辑

### 保留

```text
未改动的 token
  → tid/start/end/base/ruby/level 保留

改字只影响覆盖的 token
```

### 丢弃

```text
被删掉的 token
被改写的 token
跨切点的 token
```

### 新增

```text
新 token 新 tid
重新注音
```

### 尾部空格

```text
正文保留尾部空格
token 覆盖实际字符
token 结束后允许尾部空白
```

## 6. 保存 payload

```json
{
  "id": "r_...",
  "kind": "lyric",
  "text": "君の星",
  "t": 1.0,
  "lid": "l_aaa",
  "tokens": [
    {"tid": "t_aaa", "start": 0, "end": 1, "base": "君", "ruby": "きみ", "level": "A"}
  ],
  "trans": "你的星星"
}
```

```text
seg 由 token 的 base/ruby/level 生成。
tid 由 token 的 tid 生成。
```

## 7. 后端保存

```text
按 lid 找原行
  → 未改 token 按 tid/span/base 恢复
  → 新 token 重新分配 tid

正文改了但 token 只覆盖一部分
  → 先补齐新分段
  → 再按 tid/span/base 恢复未改部分
  → 不能因为分段不完整丢掉整行读音
```

```text
lid 找不到
  → 该行按新行处理

保存响应带 lid/tid
```

## 8. 行操作

### 拆行

```text
原内容侧保留原 lid
空侧新 lid
完整 token 迁移
跨切点 token 丢弃
译文跟随保留 lid 的一侧
```

具体：

```text
左半非空 → 左半保留 lid
左半为空 → 右半保留 lid
```

### 合并

```text
内容主体侧保留 lid
tokens 按正文顺序拼接
译文按正文顺序拼接非空部分
```

具体：

```text
左半非空 → 保留左 lid
左半为空 → 保留右 lid
```

## 9. 校验

```text
i 越界             → 忽略
目标不是 lyric     → 忽略
seg 拼接 ≠ 正文    → 忽略
h 不匹配           → 忽略
lid 重复           → 忽略后出现的
tid 数量 ≠ seg 数量 → 该行 token 丢弃
```

```text
一个坏 tid 不丢掉整行其他 tid。
失效 id 在下次保存时自然清掉。
```

## 10. 版本

```text
写入固定 v2
V1 不再支持
只接受 v2
不迁移磁盘旧文件
```

## 11. 相关

```text
格式 → nhlrc.md
单一行模型 → ../歌词数据模型.md
编辑器 → lrc-editor.md
HTTP API → http-api.md
```
