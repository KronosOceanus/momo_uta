# BUG 记录

> 记录已确认或高度可疑、**尚未修复**的问题。
> 修复后从本文移除，具体回归以 tests / git log 为准。
>
> 相关：[优化记录](优化.md) · [架构](architecture.md) · [nhlrc](topics/nhlrc.md)

## 1. 同一后台任务能启动两次

- 编号：BUG-001
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

## 2. 首次保存丢失歌词元数据

- 编号：BUG-002
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

## 3. wheel 缺少默认配置和前端静态资源

- 编号：BUG-003
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
BUG-001 并发播放
BUG-001 后台任务重复
BUG-002 元数据丢失
BUG-003 wheel 资源
```

## 说明

```text
1. 本文只记录未修复问题。
2. 修复并补回归测试后，从本文删除。
3. 记录中的「君 → you」「空 → sky」是测试 fixture，不是应用自带歌词或读音。
```
