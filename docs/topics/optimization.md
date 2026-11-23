# 优化待办

> 只记录**尚未完成**的优化项。已完成事项不在此文档保留。
> 相关格式：[nhlrc](nhlrc.md) · [nhlrc-token-ids](nhlrc-token-ids.md) · [LRC 编辑器](lrc-editor.md)。

## P0：结构风险

### 1. 合并两套正文解析器

现状：

```text
_parse_document()
  → compact lines，跳过空行

_parse_body_rows()
  → 编辑器行，保留空行
```

两份逻辑几乎相同。改时间戳、metadata、JSON 行时要同步改两处。

建议：

```text
parse_rows(text, keep_blank=..., keep_metadata=...)
  → 一次扫描

派生：
  compact_lines
  body_rows
  metadata
```

验收：

```text
空行
metadata
无时间戳草稿行
网易云 JSON 行
```

四类输入只经过一套解析逻辑。

相关：

```text
core/lrc_doc.py
```

### 2. `annotations_for` 复用统一校验

现状：

```text
annotations_and_ids_for()
  → seg + lid + tid 校验

annotations_for()
  → 重新实现一遍 seg 校验
```

风险：

```text
两套校验规则以后分叉
```

建议：

```text
annotations_for()
  → annotations_and_ids_for()[0]
```

相关：

```text
core/lrc_doc.py
```

### 3. `LRC.save` 不再要求调用方传行映射

现状：

```text
body_rows 有空行时
  → 必须传 annotation_index
  → 忘记传就写歪 annotation i
```

建议：

```text
save(body_rows, lyric_rows, annotations, ...)
```

由 core 内部计算 body → lyric 映射，调用方不传索引。

验收：

```text
正文含空行
  → 保存
  → 重新加载
  → annotation i 不错位
```

相关：

```text
core/lrc_files.py
service/song.py
service/lrc.py
```

### 4. 拆分 `save_lyrics`

现状：

[save_lyrics](../../src/nihonco_player/service/song.py#L96) 同时负责：

```text
body/compact 映射
空行
旧 annotation 对齐
token 覆盖
lid/tid 分配
翻译对齐
写文件
```

建议拆成：

```text
prepare_body_rows()
annotate_saved_lines()
resolve_line_and_token_ids()
align_saved_translations()
save_lyrics() 只编排
```

验收：

```text
空行
插入/删除行
拆行/合并
只改时间轴
只改翻译
改正文
```

每条路径都能单独测试。

## P1：编辑器边界

### 5. 拆行/合并时 lid 跟随内容

现状：

```text
在行首拆行
  → 左空行保留原 lid
  → 右边原内容拿新 lid
```

内容才是原行，身份却留在空行。

建议：

```text
哪边包含原内容主体，lid 跟哪边
另一边新 lid
```

合并同理：

```text
左边为空
  → 合并后使用右边内容的 lid
```

相关：

```text
static/20-editor.js
splitRow / mergeRows
```

### 6. 统一 token 构造

现状有三份相似逻辑：

```text
后端 _tokens_for
前端 tokensOf
前端 mergeSavedIds
```

建议：

```text
后端返回标准 token：
  tid / start / end / base / ruby / level

前端只消费，不自己从 annotations 推
```

验收：

```text
/api/lrc load
保存响应 ids
```

两处的 token 字段一致。

相关：

```text
service/lrc.py
static/20-editor.js
```

### 7. 保存回传保留 ruby/level

现状：

```text
mergeSavedIds()
  → 用服务端 tokens 覆盖
  → 新 tokens 只有 tid/start/end/base
  → ruby/level 丢失
```

目前编辑器不显示读音，所以不影响。
以后拆行/合并或显示读音时会缺字段。

建议：

```text
服务端 ids 返回 ruby/level
或前端合并时保留旧值
```

相关：

```text
service/song.py
static/20-editor.js
```

### 8. 文本输入进入撤销栈

现状：

```text
oninput
  → retokenizeRow
  → markDirty
  → 不 snapshot
```

撤销栈可能无法精确回到上一次输入。

建议：

```text
文本输入合并成一次 snapshot
或按防抖记录
```

不要每个字符都压一次栈。

相关：

```text
static/20-editor.js
```

## P2：测试与验证

### 9. 真实链路回归

需要的链路：

```text
空行 → 保存 → 重新打开
拆行 → 保存 → 再编辑
合并 → 保存 → 再编辑
保存响应 ids → 再编辑
插入/删除行 → 保存 → 重新打开
重复 token → 改一个 → 另一个保留
```

当前测试：

```text
261 Python
35 前端测试
```

缺的是跨“编辑器 → API → 文件 → 重新加载”的链路测试。

### 10. `mergeSavedIds` 的 revision 保护

已验证：

```text
保存期间编辑继续
  → revision 变
  → 不覆盖
```

仍建议补一条：

```text
保存请求返回时文本已经变了
  → 不合并旧 ids
```

## 不做

以下不属于当前优化范围：

```text
AI 讲解
完整词典
复习系统
云同步
账号
学习进度
```

产品定位保持：

```text
听歌
唱歌
校歌词
```
