# TODO

## 长期

> 长期方向与待评估项。
> 已完成事项以 git log / tests 为准。
>
> 标记：🚧 进行中；⬜ 未做；⏸ 暂缓。

### 待做

#### 1. LRC 表格整表重绘

- 状态：⬜ 未做
- 现状：很多编辑动作调用 `renderLrcTable()` 重建整个表格；短歌词无感，长歌词/连续输入时可能有布局开销。
- 可以做：只更新受影响行，或至少用 `requestAnimationFrame` 合并一帧内的重绘。
- 注意：这不是 job；是纯前端渲染优化。
- 优先级：低到中，先用实际长歌词测帧时间再决定。


---

# 代码审查（历史）

> 历史内容：仅保留尚未处理的 `LRC.save` 契约问题。
> 当前测试数量见 README。

> 记录本轮审查发现、尚未修复的问题和优化建议。
> 与 [BUG 记录](BUG.md)、[优化记录](项目整理/优化.md) 分开：本文偏代码结构和边界风险。

## 0. 当前基线

```text
457 Python 完成，1 项环境跳过
129 前端测试
前端检查通过
```

## 1. `LRC.save` 的 annotations 索引契约仍隐式

- 优先级：中
- 状态：⬜ 待修
- 位置：`core/lrc_files.py`、`service/song.py`

### 现状

`LRC.save` 同时接受：

```python
annotations
translations
line_ids
token_ids
annotation_index
```

其中：

```text
annotations / translations / line_ids / token_ids
→ 按 body 行下标
annotation_index
→ body 行下标 → compact 歌词下标
```

这个契约没有写进函数签名说明。

### 实际风险

`LRC.save` 没有收到 `annotation_index` 时，会自动生成：

```python
for bi, ln in enumerate(lines):
    if (ln.get("text") or "").strip():
        annotation_index[bi] = lyric
        lyric += 1
```

这里把 **metadata 行也当成歌词行**。

而 service 的 `_body_layout` 明确排除 metadata：

```python
if ln.get("kind") == "metadata" or is_metadata_text(text):
    continue
```

但 `service/song.py` 调用 `LRC.save` 时没有传 `annotation_index`。  
所以在带 metadata 的旧保存路径里：

```text
metadata 的 before 位置
→ _metadata_for_body 映射可能错位
```

当前 v2 编辑器主路径走 `save_rows`，不经过这段旧转换；  
但旧 lines/缓存保存仍可能触发。

### 修复方向

短期：

```text
service 调用 LRC.save 时传 annotation_index=body_to_lyric
```

彻底：

```text
所有写入先转 rows
metadata 位置直接在 rows 中表达
删除 annotation_index
旧 lines 入口只做 API 适配
```

### 测试

```text
body 前面有 metadata
→ 保存后 metadata 位置不变
→ 歌词索引不把 metadata 算进去
```

## 相关

```text
BUG 记录 → BUG.md
优化记录 → TODO.md 的「长期」
架构 → architecture.md
```
