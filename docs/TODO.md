# TODO

## Done

- [x] 人声分离只在 LRC 编辑模式自动触发
  - 普通页只同步 `vocals` 状态，不创建任务。
  - `openLrcEditor(true)` 进入成功后触发。

## Doing

## Todo

- [ ] 歌单 + nhlrc ZIP 导出/导入（见 `docs/新增功能文档/歌单与NHLRC导入导出.md`）。
- [ ] 歌单缺失歌曲灰显、保留 `missing_items`（同上文档）。
- [ ] 歌单多选右键移动到其他歌单
  - 选中歌曲（支持多选）后右键选择目标歌单，解决长列表无法拖动跨歌单的问题。

---

# 代码审查（历史）

> 历史内容：基线为 2026-11-26 的 277 Python / 42 前端，已被后续版本覆盖。
> 仅保留审查记录，不再作为当前状态；当前测试数量见 README。

> 记录本轮审查发现、尚未修复的问题和优化建议。
> 与 [BUG 记录](BUG.md)、[优化记录](优化.md) 分开：本文偏代码结构和边界风险。

## 0. 当前基线

```text
277 Python 完成，1 项环境跳过
42 前端测试
前端检查通过
```

## 1. 导出含空行的歌词会丢 lid/tid

- 优先级：高
- 状态：⬜ 待修
- 位置：`service/lrc.py` export

### 现状

```python
same_lines = [ln.get("text") for ln in lines] == [
    ln.get("text") for ln in doc["lines"]
]
lids = ... if same_lines else None
tids = ... if same_lines else None
```

`lines` 是 body 行，可能包含空行；`doc["lines"]` 是 compact 行，不含空行。

所以只要正文有空行：

```text
same_lines = False
→ 导出时 lid/tid 全部不写
```

### 影响

```text
正文、读音、翻译还在
但 nhlrc 的身份字段丢失
```

后续：

```text
导出后再导入
重复歌词
后续编辑的身份延续
```

都会退化。

### 修复方向

```text
比较非空歌词行文本
或
直接按 body_to_lyric 比较
```

保留 `lid/tid` 的映射，与保存路径一致。

## 2. 导入时 .nhlrc 无效不会回退到 .lrc

- 优先级：高
- 状态：⬜ 待修
- 位置：`core/importing.py`

### 现状

`_pick()`：

```text
.nhlrc 优先
其次较新的
```

然后只校验选中的一个：

```python
lrc = _pick(cand)
raw = lrc.read_text(...)
ok, _why = LRC.valid_import(raw)
if not ok:
    pending.append(str(a))
    added.append(str(a))
    continue
```

如果目录里同时有：

```text
歌曲.nhlrc   ← 损坏/不合法
歌曲.lrc     ← 合法
```

会选中 nhlrc，校验失败，然后直接放弃；不会尝试 lrc。

### 影响

```text
音频进入待匹配
明明有可用 LRC 却没用
```

### 修复方向

```text
按候选顺序逐个校验
第一个 valid_import 通过的才使用
```

## 3. 导入音乐+LRC 的覆盖计数不完整

- 优先级：中
- 状态：⬜ 待修
- 位置：`core/importing.py`
- 已记录：BUG-001

### 现状

音频 + LRC 主配对路径：

```python
LRC.import_text(str(a), raw, ...)
```

没有检查 `LRC.exists(a)`，也没有累加 `overwritten`。

### 影响

```text
已有 nhlrc 被覆盖
前端提示只显示“新增 N 首”
不显示“覆盖 N 首”
```

### 修复方向

```text
写 nhlrc 前检查 LRC.exists(a)
  → 计入 overwritten
```

## 4. 导入路径重复时统计可能偏大

- 优先级：中
- 状态：⬜ 待修
- 位置：`core/importing.py`
- 已记录：BUG-002

### 现状

用户同时选：

```text
audio.mp3
audio.mp3 所在目录
```

`audios` 会包含同一个文件两次。

下游：

```text
LIB.add_paths 按 file 去重
PL.add 按 uid 去重
```

但：

```text
added / pending / overwritten
```

统计可能重复。

### 修复方向

```text
收集阶段按 resolve() 去重
```

## 5. `_metadata_for_body` 跨层私有调用

- 优先级：中
- 状态：⬜ 待修
- 位置：`service/lrc.py`

### 现状

```python
LRC._metadata_for_body(...)
```

service 直接调用 core 的私有函数。

功能没问题，但边界不干净：

```text
service 不应该依赖 core 私有实现
```

### 修复方向

```text
core 暴露 metadata_for_body
或
把映射封装进 render_nhlrc
```

## 6. `LRC.save` 的 annotations 索引契约仍隐式

- 优先级：中
- 状态：⬜ 待修
- 位置：`core/lrc_files.py`、`service/song.py`

### 现状

`LRC.save` 现在会自动计算：

```text
body 行 → annotation 行
```

但 `annotations` 本身仍依赖调用方传：

```text
body-keyed
```

当前 service 是对的，但内部 API 仍有一个隐含约定：

```text
LRC.save(lines=body_rows, annotations=compact_keyed)
  → 可能写歪
```

### 修复方向

```text
显式接收 body_rows + lyric_rows
或
在 LRC.save 内部统一转换 annotations
```

## 7. 只导入音乐时，目录里的 LRC 不统计

- 优先级：低
- 状态：⬜ 待修
- 位置：`core/importing.py`

### 现状

`with_lrc=False` 时：

```text
显式选中的 .lrc
  → rejected_lrc

目录里的 .lrc
  → 不扫描
  → 不提示
```

用户选了一个包含大量 LRC 的目录时，只会看到：

```text
新增 N 首
```

不会知道目录里的歌词被忽略。

### 说明

这可能是预期语义，不一定修。

需要确认：

```text
只导入音乐
  → 目录里的 LRC 是“明确忽略”
  → 还是“提示后忽略”
```

## 建议修复顺序

```text
1. 导出含空行时保留 lid/tid
2. nhlrc 无效时回退 lrc
3. 覆盖计数
4. 路径去重
5. metadata 私有调用
6. LRC.save 的 annotations 契约
7. 目录 LRC 提示
```

## 相关

```text
BUG 记录 → BUG.md
优化记录 → 优化.md
架构 → architecture.md
```
