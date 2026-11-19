# 测试

```bash
make test                                            # 架构 + 前端 + 全部单元测试（93 条）
.venv/bin/python -m unittest tests.test_lyrics -v     # 单组
```

## 五组 93 条

| 组 | 文件 | 条数 | 测什么 |
|---|---|---|---|
| 引擎 | `test_annotate.py` | 10 | 分词、判定、档位、override |
| 引擎 | `test_invariants.py` | 10 | 7 条不变量、DP 对齐、emit 政策 |
| 引擎 | `test_romaji.py` | 11 | 假名 → 罗马音 / 键位，含往返解析 |
| 引擎 | `test_api.py` | 3 | `Annotator` 对外接口 |
| 引擎 | `test_tables.py` | 4 | 词典表加载与缺表降级 |
| 语料与评测 | `test_evalkit.py` | 10 | 打分口径（precision / coverage / 对齐差） |
| 语料与评测 | `test_aozora_parse.py` | 11 | 青空文庫解析（ruby 还原、段落切分） |
| 歌词与库 | `test_lyrics.py` | 12 | LRC 解析、歌名匹配、打分、语言判定、排除词 |
| 歌词与库 | `test_library.py` | 5 | 扫目录、缓存命中、标签读写 |
| 播放器 | `test_player_http.py` | 6 | 起真服务打接口（随机端口，不联网） |
| 播放器 | `test_playlists_api.py` | 10 | 歌单建/删/清空/移动/排序/默认锁定 + 读音持久化 |
| 界面 | `test_ui_smoke.py` | 1 | **冒烟**：真开 pywebview 窗口，断言歌单渲染、点歌出歌词、无 JS 错误 |

## 三档策略

```text
① 纯函数      最多，毫秒级，改逻辑必跑
② HTTP 端到端  ThreadingHTTPServer(port=0) + urllib
              能抓：路由被删、NameError、字段丢失
③ 界面冒烟    pywebview 真窗口（约 9 秒，需要桌面环境）
              无 GUI / 没装 pywebview → 自动 skip，不会让 CI 失败
```

## 前置检查（也在 make test 里）

```text
scripts/check_arch.py   Python import 边界（见 docs/architecture.md §2）
scripts/check_js.py     前端三文件语法 + 合并后再检查（抓跨文件重复定义）
```

## 写测试时的约定

```text
· 不联网：抓歌词的测试一律 patch 掉网络层
· 不写真实用户数据：edits / playlists / song_meta 都用 set_file 指到临时文件
· 不依赖顺序：每个测试自己准备数据，跑单条也能过
· 断言行为而不是实现：改内部结构时，测试不该跟着改
```

## 为测试做过的两处让步

```text
1) playlists.set_file / edits.set_file：允许测试把存储指到临时文件
2) server.make_server(port=0)：随机端口，避免测试互相抢占
```

## 界面冒烟挡住过什么（真实案例）

```text
· 整块替换 HTML 时把「振假名工具行」一起删了 → 页面脚本报错，前端全挂
· server.py 重新定义 _edit 后旧版本覆盖新版本 → 接口 500
· 音频路由被删 → 播放条显示 0:00、原生元素报错
以上都是"单测全绿、界面已死"的类型，只有冒烟能抓
```

## 还没覆盖的

```text
· 音频真的出声（WebView 行为，Python 侧测不了）
· 拖拽导入 / 拖拽排序
· LRC 编辑器的多选、框选、粘贴细节
· 长时间播放的内存与波形帧率
```
