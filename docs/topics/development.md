# 开发与测试

> 面向维护者：常用命令、检查器边界、日志、缓存清理和开发入口。

## 0. 常用命令

```bash
make test          # 完整检查
make test-python   # Python 架构 + unittest
make arch          # 当前实现包含 check_arch + check_js
make app           # 启动桌面应用
make api           # 命令行验证引擎
# 首次测试：
pip install -e '.[dev]'

./packaging/build.sh thin|full  # 构建 .app
```

```bash
make clean-cache   # lyrics / wave / annotations
make clean-index   # library_index / fingerprints
make clean-vocals  # vocals / tmp vocals
make clean-tmp     # data/tmp
```

## 1. 安装

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

人声分离可选：

```bash
.venv/bin/python -m pip install -e '.[vocals]'
```

```text
Python 3.11+
macOS 桌面依赖：pywebview + pyobjc
Node.js：前端 VM 测试和 check_js 需要
```

## 2. 测试入口

### `make test`

```text
make arch
  → check_arch.py
  → check_js.py

make test-python
  → unittest discover

node --test
  → lrc_editor.test.cjs
  → state_machine.test.cjs
  → audio_engine.test.cjs
```

### `make test-python`

```text
check_arch.py
  + 所有 Python unittest
```

### `make arch`

```text
check_arch.py：Python 静态 import 前缀
check_js.py：前端语法 / IIFE / window.NH / 拼接检查
```

```text
make arch 不跑业务测试。
```

## 3. 检查器能力边界

### `check_arch.py`

```text
只检查 Python 静态 import 前缀
不查运行时动态 import
不查行为
不查前端
```

```text
允许向下跨层。
HTTP 直接 import core 不是违规。
```

### `check_js.py`

```text
每个脚本单独 node --check
按 ORDER 拼接后再检查
每个脚本必须是 IIFE
必须取 window.NH
```

```text
不查运行时行为。
不保证 DOM 事件正确。
```

## 4. 前端脚本顺序

```text
05-audio.js
06-state.js
10-app.js
11-vocals.js
12-library.js
20-editor.js
30-playback.js
40-shortcuts.js
```

```text
classic script，无构建器。
所有脚本共享 window.NH。
新增脚本必须同步：
  player.html
  scripts/check_js.py ORDER
  tests/lrc_editor.test.cjs scripts 列表
```

## 5. 测试改动域

| 改动 | 回归 |
|---|---|
| 分层 / import | `make arch` |
| nhlrc / 翻译 / offset | Python 领域测试 |
| nhlrc rows / 行身份 / 导出 | `test_lyric_rows.py` + `test_v2_integration.py` |
| 切歌 / 保存 / 音频 | 前端 VM 测试 |
| API / 跨层 | `make test` |
| 前端脚本装配 | `check_js.py` + `lrc_editor.test.cjs` |

## 6. 日志

```text
data/cache/app.log
```

```text
diag.log      普通记录
diag.exception 完整 traceback
```

```text
HTTP 未捕获异常
job 失败
人声失败
前端上报异常
```

```text
日志写入失败不会抛异常。
```

## 7. 调试入口

```bash
make api
.venv/bin/python -m momo_yomi.annotate --stdio
.venv/bin/python -m momo_uta_app
```

```text
app 使用随机端口，不占固定端口。
静态前端由 routes 直接服务。
```

## 8. 打包

```bash
./packaging/build.sh thin
./packaging/build.sh full
```

```text
产物在 dist/<variant>/
zip 在 dist/
```

```text
打包后用户数据：
  ~/Library/Application Support/momo uta/data
开发时数据：
  <repo>/data
```

## 9. 数据安全

```text
不要用测试写真实 data/curated、data/lyrics。
测试使用 set_file / patch 指向临时目录。
```

```text
make clean-cache / clean-index / clean-vocals 只删可重建数据。
权威 nhlrc / playlists / song_meta / imports 不在清理命令里。
```

## 10. 已知边界

```text
1. 没有前端构建器，新增脚本要手动改加载顺序。
2. check_js 只做静态检查。
3. 测试有共享 CACHE 需要 setUp/tearDown 维护。
4. 人声测试依赖外部 demucs/ffmpeg，通常不跑真实分离。
5. 打包尚未纳入 Makefile。
```

## 11. 相关

```text
architecture.md
cache.md
http-api.md
packaging.md
```
