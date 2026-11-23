# nhlrc 数据结构升级：行 ID 与 token ID

> 目标：编辑一行正文时，未改动的 token 读音不被整行重置。
> 格式基础见 [nhlrc](nhlrc.md)。
>
> 状态：已实现后端读写、API、编辑器加载/保存、文本编辑和拆行/合并。
> 空行规则已并入 [nhlrc](nhlrc.md) 的正文格式。

## 0. 一句话

```text
lid = 行身份
tid = token 身份
i   = 当前显示位置
h   = 当前正文 hash
```

```text
身份不再由行号、行 hash、token 文本或位置推断。
```

## 1. 为什么需要升级

当前 nhlrc：

```json
{
  "i": 0,
  "h": "a1b2c3d4",
  "seg": [["君", "きみ", "A"], ["の", null, "K"]]
}
```

问题：

```text
正文改一个字
  → h 变
  → 整行 annotation 失效
  → 整行 ruby 重新生成
```

现有“保守 token 对齐”只能按字符区间尽量保留：

```text
不误保留
但不能解决：
  · 行插入/删除后行身份
  · token 内部改动
  · 重复 token 的绝对身份
```

升级后：

```text
行有 lid
token 有 tid
前端携带身份
后端只按身份合并
```

## 2. 新格式

仍然保持：

```text
v: 1
body 不变
正文不变
trans 不变
seg 仍然是 [base, ruby, level]
```

只增加两个可选字段：

```json
{
  "i": 0,
  "h": "a1b2c3d4",
  "lid": "l_8f3a2c1d",
  "seg": [
    ["君", "きみ", "A"],
    ["の", null, "K"],
    ["名前", "なまえ", "A"]
  ],
  "tid": ["t_91ab77cd", "t_77cd42ef", "t_42ef91ab"]
}
```

### 2.1 字段规则

```text
i     非空歌词行号；空行不占号，仅用于显示/读写顺序
h     当前正文 hash，仅用于快速校验
lid   行身份，跨插入/删除/移动保持不变
seg   [base, ruby, level]
tid   与 seg 一一对应的 token 身份
```

```text
lid 在整首歌内唯一
tid 在整首歌内唯一
```

```text
lid/tid 不是按 base、行号或行 hash 生成的。
```

### 2.2 可选性

```text
旧文件没有 lid/tid
  → 正常读
  → 内存生成 legacy id
  → 不立即写回

新文件保存
  → 写入 lid/tid

旧程序读新文件
  → 忽略未知字段
  → 仍按 seg 读取
```

不需要迁移。

## 3. 身份规则

### 3.1 行身份

```text
lid 跟行内容无关
```

```text
改文字
  → lid 不变

改时间
  → lid 不变

改翻译
  → lid 不变

上下移动
  → lid 不变

插入一行
  → 新 lid

删除一行
  → 删除 lid
```

### 3.2 token 身份

```text
tid 跟 token 身份绑定，不跟文本绑定
```

```text
token 文本不变
  → tid 不变
  → ruby/level 保留

token 文本变了
  → 旧 tid 不保留
  → 新 token 新 tid

token 被删除
  → tid 删除

两个 token 合并
  → 新 tid
  → 重新注音
```

### 3.3 重复 token

```text
君の君
```

两个 `君` 各有自己的 tid：

```text
第一个君 → t_a...
第二个君 → t_b...
```

改掉其中一个，另一个的读音不会错位。

## 4. legacy ID

旧文件没有 ID 时，读取时内存生成。

```text
lid = l_ + hash(旧行文本 + 行位置)[:8]
tid = t_ + hash(旧行文本 + token 位置 + base)[:8]
```

要求：

```text
同一份旧文件重复读取
  → legacy id 相同

不写回文件
  → 不产生迁移

保存一次后
  → 写正式 lid/tid
```

## 5. 前端数据模型

`EROWS` 每行增加：

```js
{
  t: 12.3,
  text: "君の名前",
  trans: "",
  lid: "l_8f3a2c1d",
  tokens: [
    { tid: "t_91ab77cd", start: 0, end: 1, base: "君", ruby: "きみ", level: "A" },
    { tid: "t_77cd42ef", start: 1, end: 2, base: "の", ruby: null, level: "K" },
    { tid: "t_42ef91ab", start: 2, end: 4, base: "名前", ruby: "なまえ", level: "A" }
  ]
}
```

```text
start/end 是当前 text 内的字符偏移
tokens 只保存有身份的 token
新插入的 token 可以暂时没有 tid
```

## 6. 文本编辑协议

用户在原文输入框里改字时，前端做字符级 diff。

### 6.1 保留

```text
token 完整落在未变区间
  → 保留 tid
  → 保留 ruby/level
  → start/end 平移到新位置
```

### 6.2 丢弃

```text
token 跨过改动边界
  → 不保留 tid
  → 后端重新分词/注音
```

### 6.3 新增

```text
新插入文字
  → 没有 tid
  → 后端重新注音
  → 分配新 tid
```

示例：

```text
旧：君の名前
新：君の名
```

```text
君   → tid 保留
の   → tid 保留
名前 → 删除
名   → 新 token
```

```text
如果改动发生在 token 内部：
旧：名前
新：名
  → 旧 tid 不保留
  → 新 token
```

## 7. 保存 payload

LRC 保存时，每行发送：

```json
{
  "t": 12.3,
  "text": "君の名",
  "trans": "",
  "lid": "l_8f3a2c1d",
  "tokens": [
    {"tid": "t_91ab77cd", "start": 0, "end": 1, "base": "君"},
    {"tid": "t_77cd42ef", "start": 1, "end": 2, "base": "の"}
  ]
}
```

规则：

```text
tokens 只带身份和 span
ruby/level 以后端旧文件为准
新 token 不带 tid
空行不进入 tokens，也不占 i
```

```text
后端不根据 base 猜 tid
```

## 8. 后端保存

新增保存模式：

```text
mode = "tokens"
```

流程：

```text
1. 读旧 nhlrc
2. 建立 tid → (base, ruby, level)
3. 建立 lid → 旧行 annotation
4. 遍历新 lines
5. 对新行重新注音
6. 对 payload 里的 token：
   - 检查 start/end/base
   - 找新注音中 span/base 完全一致的 segment
   - 找到则沿用旧 ruby/level
7. 对没有覆盖的 segment：
   - 用新引擎结果
   - 分配新 tid
8. 写回 nhlrc
```

关键：

```text
只按 tid + span 对应
不按 base 做 LCS
不按位置猜测
```

## 9. 行操作规则

| 操作 | lid | token |
|---|---|---|
| 插入行 | 新 lid | 无 |
| 删除行 | 删除 | 删除 |
| 上下移动 | 不变 | 不变 |
| 改时间 | 不变 | 不变 |
| 改正文 | 不变 | 未变 token 保留 |
| 拆行 | 原行保留，新行新 lid | 完整 token 可保留 |
| 合并行 | 保留左行 lid | 完整 token 可保留 |

### 9.1 拆行

```text
原行保留 lid
新行生成新 lid
跨拆分点的 token 去掉 tid
```

### 9.2 合并行

```text
保留左边 lid
右边 lid 删除
跨合并点的 token 去掉 tid
```

## 10. 校验

保存时必须检查：

```text
tid 不重复
lid 不重复
start/end 合法
tokens 不重叠
base == text.slice(start, end)
tid 与旧文件中的 token 能对应
```

失败时：

```text
丢弃该 token 的 tid
回退引擎注音
不拒绝整首歌
```

## 11. 兼容策略

```text
新代码读旧文件
  → 缺 lid/tid 就生成 legacy id

旧代码读新文件
  → 忽略 lid/tid
  → seg 仍按三元组读取

旧缓存
  → 不清
```

```text
不设计迁移脚本
不双读旧字段
不升级 v
```

## 12. 实施阶段

### 第 1 步：后端格式

```text
lrc_doc 读写 lid/tid
lrc_files 返回 IDs
legacy id 生成
测试：旧文件、新文件、ID 唯一性
```

### 第 2 步：API

```text
/api/lrc load 返回 lid/tokens
/api/lrc save 接受 lid/tokens
```

### 第 3 步：前端加载

```text
EROWS 保存 lid/tokens
savePayload 带 lid/tokens
```

### 第 4 步：文本编辑

```text
输入 diff
更新 token span
保留/丢弃 tid
```

### 第 5 步：行操作

```text
addRow / delRows / 拆行 / 合并 / 粘贴
维护 lid/tid
```

### 第 6 步：回归

```text
改一行中间
改 token 内部
重复 token
插入行
删除行
上下移动
拆行
合并行
撤销/重做
自动保存
```

## 13. 不做

```text
不做旧数据迁移
不做 sidecar 文件
不做跨歌曲 token id
不做 token 级 CRDT
不把 tid 放进正文
```

## 14. 最终效果

```text
改时间     → 整行原样
改翻译     → 整行原样
改一处字   → 只重算该 token
重复 token → tid 区分
插入/删除  → lid 区分
拆/合并    → 完整 token 保留
```

## 15. 空行

空行属于正文，但不属于注音。

```text
body_rows = 编辑器行，保留空行
lines     = 非空歌词行
i         = lines 的序号
```

保存：

```text
正文按 body_rows 渲染
annotation / trans / lid / tid 按 lines 编号
```

所以：

```text
在注音行前插入空行
  → 正文多一行
  → annotation i 不变
  → 后面的读音不会被整体错位
```

相关格式：

```text
nhlrc 正文空行 → nhlrc.md 第 3.4 节
```

## 16. 保存回传

保存响应可以带：

```json
{"ids": [
  {"i": 0, "text": "君の名", "lid": "l_...", "tokens": [
    {"tid": "t_...", "start": 0, "end": 1, "base": "君",
     "ruby": "きみ", "level": "A"}
  ]}
]}
```

编辑器在 revision 未变时把这些身份合并回 `EROWS`。

```text
新 token 的 tid
  → 不需要重新打开编辑器
  → 后续编辑仍然可以按身份保留
```

## 17. 失效身份清理

加载时：

```text
annotation 无效
  → 不进入 annotations

lid/tid 格式不合法
  → 回退 legacy id

lid/tid 重复
  → 后出现的回退 legacy id

tid 数量 ≠ seg 数量
  → 该行 token id 回退 legacy id
```

写入时：

```text
合法且不重复的 lid/tid
  → 保留

非法/重复的单个 tid
  → 生成新的合法 tid
  → 同一行其他 tid 不受影响

不写失效 annotation
不写被删除行的身份
```

```text
不在加载时偷偷重写文件。
下一次用户保存后，失效身份自然被清掉。
```

## 18. 相关

```text
nhlrc 格式 → nhlrc.md
LRC 编辑器 → lrc-editor.md
```
