# 测试

```bash
make test                       # 全部（93 条）
.venv/bin/python -m unittest tests.test_lyrics -v      # 单组
```

## 分四组

| 文件 | 条数 | 测什么 |
|---|---|---|
| `tests/test_annotate.py` | 引擎主流程：分词、判定、档位、override |
| `tests/test_invariants.py` | 7 条不变量、DP 对齐、emit 政策 |
| `tests/test_evalkit.py` | 打分口径（precision / coverage / 对齐差） |
| `tests/test_api.py` | `Annotator` 对外接口 |
| `tests/test_romaji.py` | 假名 → 罗马音 / 键位，含往返解析 |
| `tests/test_lyrics.py` | LRC 解析、歌名匹配、打分、语言判定、排除词 |
| `tests/test_player_http.py` | 起真服务打 6 个接口（随机端口，不联网） |
| `tests/test_library.py` | 扫目录、缓存命中、标签读写 |
| `tests/test_playlists_api.py` | 歌单接口（建/删/清空/移动/排序/默认锁定）与读音持久化 |
| `tests/test_ui_smoke.py` | **界面冒烟**：真开 pywebview 窗口，断言歌单渲染、点歌出歌词、无 JS 错误 |

## 三档测试策略

```text
① 纯函数     最多，跑得快（毫秒级），改逻辑必跑
② HTTP 端到端 起 ThreadingHTTPServer(port=0)，用 urllib 打接口
             能抓：路由被删、NameError、字段丢失
③ 界面冒烟    pywebview 起真窗口跑一遍（约 9 秒，需要桌面环境）
             无 GUI / 没装 pywebview → 自动 skip，不会让 CI 失败
```

## 写测试时的约定

```text
· 不联网：歌词抓取一律打桩（monkeypatch LY.get_lrc）
· 不碰真实音乐目录：用 tempfile.TemporaryDirectory 造假文件
· 不碰真实缓存：把 LY.CACHE 指到临时目录
· 断言写"行为"不写"实现"：例如断言 ruby 里有 <rt>か</rt>，不是断言整串 HTML
```

## 为测试做过的两处让步

```text
library.scan_library(folder=None)   可传目录（默认 ~/Music/网易云音乐）
server.make_server(port=0)          可起随机端口
```

两个参数都只影响测试，生产时用默认值。

## 界面冒烟挡住过什么（真实案例）

```text
· 重写列表区时漏声明 EDITMODE        → 页面 ReferenceError，列表空
· 整段替换时删掉了 load() / navIdx() → 点歌没反应
· 漏掉启动时那句 loadLib()           → 页面从不请求歌单
三者都是"代码能跑但页面是死的"，纯函数测试完全测不出来。
```

断言内容：

```text
.pl 数量 > 0            歌单渲染
.it 数量 > 0            条目渲染
点第一首后 #lyr .ln > 0  点歌后歌词出现
#rmcol .ln2 > 0         右侧罗马音出现
页面无 JS 错误（含 unhandledrejection）
```

## 还没覆盖的

```text
· 候选弹层、编辑输入框、localStorage 恢复、IME 回车
· 拖拽（歌单排序、歌曲跨歌单移动）
· 导入流程（原生文件对话框无法自动化）
· 歌词抓取的网络路径（MB / 网易云真实返回）
· 音频播放（浏览器行为，Python 侧无法测）
```
