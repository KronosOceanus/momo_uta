# BUG 记录

> 记录已确认或高度可疑、**尚未修复**的问题。
> 修复后从本文移除，具体回归以 tests / git log 为准。
>
> 相关：[优化记录](优化.md) · [架构](architecture.md) · [nhlrc](topics/nhlrc.md)

## 1. 重复歌词的读音 / token ID 跟错行

- 编号：BUG-001
- 状态：⬜ 待修
- 优先级：高
- 影响：交换或移动重复歌词后，读音和 token 身份留在原位置
- 复现：已确认

### 现象

```text
两行都是「君」：
  第一行 きみ
  第二行 くん

交换两行后保存：
  lid 跟着行移动了
  但读音仍是第一行 きみ、第二行 くん
  token ID 也没有跟着移动
```

### 原因

`service/song.py` 的 `_annotate_lines()` 有一个快速路径：

```python
if keep_unchanged and st and "".join(x[0] for x in st) == text:
    ann[i] = st
    continue
```

它在 token 覆盖之前直接返回。

重复行文本相同：

```text
align_annotations 只能按文本 FIFO 匹配
  → 旧 0「君」のきみ 配给新 0「君」
  → 旧 1「君」のくん 配给新 1「君」
```

于是：

```text
lid/tokens 已经交换
annotation 仍按位置保留
```

### 方向

```text
1. 行上带 tokens/lid 时，不要走 keep_unchanged 快速路径
2. 重复行按 lid 对齐，不按文本 FIFO
3. token 覆盖必须优先于旧 annotation
```

### 相关

```text
src/nihonco_player/service/song.py: _annotate_lines / _annotate_for_save
src/nihonco_player/core/lrc_doc.py: align_annotations
```

## 2. 并发播放后暂停可能还有声音

- 编号：BUG-002
- 状态：⬜ 待修
- 优先级：高
- 影响：双音源叠加，暂停不彻底
- 复现：代码路径已确认，GPT 用模拟 Web Audio 复现

### 现象

解码期间连续发出两次播放请求，解码完成后启动两个音源。暂停只停掉其中一个。

### 原因

`static/05-audio.js` 的 `play()`：

```js
if(this._playing) return;
if(!this._buf) await this.preload();
...
this._startSrc();
```

两个 `play()` 可以同时通过 `_playing` 检查，并同时等待同一个 preload；完成后都调用 `_startSrc()`。

```text
_playing 只在 _startSrc() 里变成 true
  → 前置检查挡不住第二个
```

### 方向

```text
1. play 加互斥 Promise / 生成序号
2. await 后再检查 _playing / seq / url
3. _startSrc 前保证只有一个 pending starter
```

### 相关

```text
src/nihonco_player/static/05-audio.js: play / _startSrc
```

## 3. 同一后台任务能启动两次

- 编号：BUG-003
- 状态：⬜ 待修
- 优先级：中高
- 影响：人声分离等昂贵任务重复执行，资源和取消状态错乱
- 复现：并发路径已确认

### 现象

两个并发请求提交相同 `kind + key`：

```text
返回两个 job ID
runner 执行两次
```

### 原因

`core/jobs.py` 的 `start()`：

```python
active = find_active(kind, str(key))
if active:
    return active

job_id = uuid.uuid4().hex
with _lock:
    _jobs[job_id] = job
```

`find_active` 和插入不在同一个锁段：

```text
A、B 同时 find_active → None
A 插入 job A
B 插入 job B
```

### 方向

```text
find_active + 插入放进同一个 _lock 临界区
```

### 相关

```text
src/nihonco_player/core/jobs.py: start / find_active
```

## 4. 首次保存丢失歌词元数据

- 编号：BUG-004
- 状态：⬜ 待修
- 优先级：中
- 影响：`[ar:]`、`[ti:]`、`[offset:]` 等元数据丢失
- 复现：代码路径已确认

### 现象

从歌词缓存加载时能看到：

```text
[ar:歌手]
```

首次保存为 `.nhlrc` 后重新加载，字段消失。

### 原因

`core/lrc_files.py` 的 `save()`：

```python
original = 旧 nhlrc 内容
body, _tail = _split_nhlrc(original)
_, metadata = _parse_document(body)
```

首次保存：

```text
original = ""
metadata = []
```

编辑行里没有 metadata，`save()` 又没有从当前 doc 接收 metadata，于是写入空。

### 方向

```text
save() 接收当前 metadata
  或
从 load 的 doc 带入
```

### 相关

```text
src/nihonco_player/core/lrc_files.py: save
src/nihonco_player/service/song.py: save_lyrics
```

## 5. wheel 缺少默认配置和前端静态资源

- 编号：BUG-005
- 状态：⬜ 待修
- 优先级：中
- 影响：`pip install` 后命令入口运行时报错
- 复现：离线 wheel 安装检查已确认
- 范围：wheel，不代表 macOS `.app` 构建

### 现象

普通非 editable 安装生成 `nihonco-uta` 命令，但运行时找不到：

```text
config/defaults.json
前端 static 资源
```

### 原因

`pyproject.toml` 只配置了：

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

没有把非 Python 数据文件打进 wheel。

### 方向

```text
1. 补充 package-data / include-package-data
2. 确认 config/defaults.json 和静态资源进入 wheel
3. 用干净虚拟环境做一次非 editable 安装检查
```

```text
不要用 .app 能运行来证明 wheel 没问题。
```

### 相关

```text
pyproject.toml
```

## 修复顺序建议

```text
BUG-001 翻译错行/丢失
BUG-001 重复歌词身份错位
BUG-002 并发播放
BUG-003 后台任务重复
BUG-004 元数据丢失
BUG-005 wheel 资源
```

## 说明

```text
1. 本文只记录未修复问题。
2. 修复并补回归测试后，从本文删除。
3. 记录中的「君 → you」「空 → sky」是测试 fixture，不是应用自带歌词或读音。
```
