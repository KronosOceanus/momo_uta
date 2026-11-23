# BUG 记录

> 记录已确认或高度可疑、**尚未修复**的问题。
> 修复后从本文移除，具体回归以 tests / git log 为准。
>
> 相关：[优化记录](优化.md) · [架构](architecture.md) · [nhlrc](topics/nhlrc.md)

## 0. 导入音乐+LRC 覆盖 nhlrc 时不计入 overwritten

- 编号：BUG-000
- 状态：⬜ 待修
- 优先级：高
- 影响：覆盖已有 nhlrc，但前端只显示“新增 N 首”
- 范围：`core/importing.import_paths`

### 现象

音频和同名 LRC 一起导入，且已有 nhlrc：

```text
实际：nhlrc 被覆盖
提示：新增 1 首
缺少：覆盖 1 首
```

### 原因

`overwritten` 只在“剩余 LRC 反查音频”阶段增加：

```python
had = LRC.exists(target)
if had:
    overwritten += 1
```

但音频 + LRC 配对主路径：

```python
LRC.import_text(str(a), raw, ...)
```

没有检查 `LRC.exists(a)`，也没有累加 `overwritten`。

### 修复方向

```text
主配对路径写 nhlrc 前也检查 LRC.exists(a)
  → 计入 overwritten
```

### 测试

```text
已有 nhlrc
  → 导入音乐+LRC
  → overwritten == 1
```

### 相关

```text
src/nihonco_player/core/importing.py: import_paths
```

## 2. 导入路径重复时，统计可能偏大

- 编号：BUG-002
- 状态：⬜ 待修
- 优先级：中
- 影响：重复计数、重复写，虽然下游会去重
- 范围：`import_paths`

### 现象

用户同时选择：

```text
audio.mp3
audio.mp3 所在目录
```

同一个音频进入 `audios` 两次。

下游：

```text
LIB.add_paths 会按 file 去重
PL.add 会按 uid 去重
```

但 `added`、`pending`、`overwritten` 的统计可能重复。

### 原因

收集阶段没有按 resolved path 去重。

### 修复方向

```text
audios = unique([p.resolve() ...])
lrcs   = unique([p.resolve() ...])
```

### 测试

```text
同时选文件和父目录
  → added 只有一个
  → 统计不重复
```

### 相关

```text
core/importing.py: import_paths
```

## 3. 导入模块残留死代码

- 编号：BUG-003
- 状态：⬜ 待修
- 优先级：低
- 影响：维护风险；旧自动配对逻辑可能被误用
- 范围：`core/importing.py`

### 现状

没有调用：

```text
_annotations()
_pair()
_body() 只被 _pair 使用
```

`_pair()` 还是旧版自动配对逻辑，不带 `with_lrc` 语义。

### 修复方向

```text
删除 _annotations / _pair / _body
让 import_paths 成为唯一导入入口
```

### 相关

```text
src/nihonco_player/core/importing.py
```

## 4. `doImport` 的 `btn` 参数没有实际意义

- 编号：BUG-004
- 状态：⬜ 待修
- 优先级：低
- 影响：无功能崩溃，但参数误导
- 范围：`static/12-library.js`

### 现状

```js
async function doImport(listId, withLrc, btn)
```

菜单调用：

```js
doImport(g.id, false)
```

`btn` 是 `undefined`。

`lock(btn, false)` 里虽然判断了 `if(btn)`，不会崩，但这个参数没有意义。

### 修复方向

```text
删除 btn 参数
或
真正传入触发按钮
```

### 相关

```text
src/nihonco_player/static/12-library.js: doImport
```

## 修复顺序

```text
BUG-001 覆盖计数
BUG-002 路径去重
BUG-003 死代码
BUG-004 doImport btn
```
