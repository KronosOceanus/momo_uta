# 架构

> 这份文档定义**层次、边界、依赖方向**。改代码前先看这里，确认"该改哪个文件"。
> 现状与目标的差异在 §7，按步骤迁移。

## 1. 三层 + 一个壳

```text
┌──────────────────────────────────────────────┐
│ nihonco_player_app/   窗口壳（pywebview）     │  只负责：起服务、开窗口、原生对话框
└──────────────────────────────────────────────┘
                    ↓ 只调 http
┌──────────────────────────────────────────────┐
│ nihonco_player/http/  HTTP 入口               │  只负责：解析参数、转发、返回
│ nihonco_player/service/ 业务编排              │  一个动作一个函数
│ nihonco_player/core/  数据与规则              │  只碰文件与纯逻辑
└──────────────────────────────────────────────┘
                    ↓ 只调引擎
┌──────────────────────────────────────────────┐
│ nihonco_yomi/  标注引擎（纯计算）             │  不联网、不读歌、不开服务
└──────────────────────────────────────────────┘
```

## 2. 依赖规则（硬约束）

| 层 | 可以 import | 禁止 import |
|---|---|---|
| `nihonco_yomi` | 标准库、sudachipy、自身 | 任何 `nihonco_player*` |
| `core` | 标准库、`nihonco_yomi`、同层 `core` | `service`、`http`、`static` |
| `service` | `core`、`nihonco_yomi` | `http`（不能自己发 HTTP），前端 |
| `http` | `service`、`core`、标准库 | 不写业务逻辑（每个 handler ≤ 10 行） |
| `nihonco_player_app` | `http`（启动）、pywebview | `core`/`service` 的具体实现 |

```text
检查方式：scripts/check_arch.py（阶段 3 提供）
  扫描各包的 import，违反上表就报错退出
```

## 3. 目录（目标）

```text
nihonco_yomi/
  annotate.py romaji.py counters.py invariants.py kana.py llm.py
  render.py            注音 HTML 的唯一实现
  paths.py thresholds.py config.py
  serve.py             标注测试页（可选工具，不属于产品路径）

nihonco_player/
  core/
    library.py         扫目录、缓存索引、导入路径登记
    playlists.py       歌单（uid 集合 + 文件锁）
    lyrics_text.py     歌词文本：解析 / 名字匹配 / 语言判定
    lyrics_cache.py    歌词缓存键与读写
    lyrics_fetch.py    网易云 / MB / lrclib + 挑选
    lyrics.py          门面（对外只暴露这一层）
    lrcio.py           .lrc 读写、备份、恢复、JSON 歌词兼容
    waveform.py        ffmpeg → 峰值 → 缓存
    importing.py       导入的四种输入
    edits.py           手改读音
    song_meta.py       每首歌的 offset
  service/
    song.py            payload 装配、改读音、重新匹配、选候选、懒匹配
    playlist.py        歌单动作
    importing.py       导入动作（扫描 → 落库 → 归入歌单）
    lrc.py             保存 / 备份 / 恢复 / 导入 LRC 文本
  http/
    routes.py          路由表 + handler
    static.py          静态文件、音频流（Range）
  static/
    player.html
    player.css
    10-app.js          状态、工具、歌单、载入单曲、右侧面板
    20-editor.js       LRC 表格（对齐、增删、粘贴、保存联动）
    30-playback.js     统一时间语义、自绘播放条、波形跟随、键盘
  web.py              页面装配（注入配置）

nihonco_player_app/
  __main__.py          窗口壳 + 原生对话框
```

## 4. 数据流

### 4.1 打开一首歌

```text
点击列表项
  → app.js: GET /api/song/<idx>
  → http/routes → service/song.payload(idx)
      → core/library.CACHE 取条目
      → core/lyrics.get_lrc（缓存优先）
      → nihonco_yomi.Annotator 标音
      → edits.for_song 叠加手改读音
      → song_meta 取 offset
  ← { lines[{t, text, ruby, rm, ky}], edits, offset }
```

### 4.2 播放与跳句（一套时间语义）

```text
生效时间 = 行时间 + offset
当前行   = 最后一个「生效时间 ≤ 播放时间」的非 meta 行
跳句     = 在非 meta 行序列里前后移动
循环     = 锚定开启时所在行
两种编辑模式共用这套，只是高亮画在不同 DOM 上
```

### 4.3 导入

```text
选目录/文件 → http POST /api/pl {action:"import"}
  → service/importing.run(list, paths)
      → core/importing.scan（目录递归 / 音频+lrc 配对 / 纯 lrc 反查）
      → core/lyrics.write_local_lrc（写缓存）
      → core/playlists.add（uid 入歌单）
```

### 4.4 LRC 编辑保存

```text
编辑表格（editor.js）
  → 停手 1.5 秒 或 点保存
  → POST /api/lrc {action:"save", lines}
  → service/lrc.save
      → core/lrcio.save（首次备份 .lrc.bak + 原子写）
      → core/lyrics.write_local_lrc（同步缓存，播放器立刻生效）
```

## 5. 谁写哪个文件（数据所有权）

| 文件 | 唯一写入者 | 可重建 |
|---|---|---|
| `data/curated/playlists.json` | `core/playlists.py` | 否 |
| `data/curated/readings.json` | `core/edits.py` | 否 |
| `data/curated/song_meta.json` | `core/song_meta.py` | 否 |
| `data/curated/song_tags.json` | `core/library.py` | 否 |
| `data/curated/imports.json` | `core/library.py` | 是（丢"导入"歌单条目） |
| `data/cache/lyrics/*.json` | `core/lyrics_cache.py` | 是 |
| `data/cache/wave/*.json` | `core/waveform.py` | 是 |
| 音频同目录 `*.lrc` / `*.lrc.bak` | `core/lrcio.py` | 否（用户资产） |
| `data/config.json` | 人 | 是 |
| `config/defaults.json` | 仓库 | 否 |

```text
写用户数据的模块都加 fcntl 文件锁（playlists / edits / song_meta）
缓存类不加锁：最坏是重复计算
```

## 6. 扩展点（怎么做一件事）

| 想做的事 | 改哪里 |
|---|---|
| 加一个接口 | `http/routes.py` 表里加一行 + `service/*` 加函数 |
| 加一个数据字段 | 对应的 `core/*` 模块 + `service/song.payload` |
| 加一个前端面板 | `static/` 新模块 + `app.js` 挂载 |
| 加一种导入来源 | `core/importing.py` + `service/importing.py` |
| 改判定规则 | `nihonco_yomi/thresholds.py`（A 类，改完必须重跑评测） |
| 改运行参数 | `config/defaults.json`（B 类，重启生效） |

## 7. 现状与目标的差距（迁移步骤）

```text
第 1 步  后端拆分 —— ✅ 已完成
  core/    library playlists lyrics* lrcio waveform importing edits song_meta
  service/ song.py playlist.py lrc.py
  http/    routes.py static.py server.py
  server.py 只剩 16 行兼容壳（app 壳与测试继续 from nihonco_player import server）

第 2 步  前端拆分 —— ✅ 已完成（按加载顺序切文件，共享全局作用域）
  尝试过改 ES module 并已放弃，原因记录如下：
    三个文件互相调用（10↔20↔30 都有），转换成 module 需要把每个全局名改成
    st.xxx。但全局名和函数内的局部变量重名（例如 ids / lock / WAVE），
    纯文本替换会把局部变量也改掉 → 直接语法错误。
    要安全转换必须先做作用域分析（或每个名字都改掉），风险远大于收益。
  static/10-app.js      365 行  状态、工具、歌单、载入单曲、右侧面板
  static/20-editor.js   509 行  LRC 表格（对齐、增删、粘贴、保存）
  static/30-playback.js 244 行  时间语义、播放条、波形跟随、键盘
  为什么不是 ES module：全局状态（S/LINES/EROWS/OFFSET…）被三个文件直接读写，
  拆成 module 需要把上千处引用改成容器对象，风险大于收益。
  以后要做，建议一次只改一个文件、每步跑冒烟。

第 3 步  约束固化 —— ✅ 已完成
  scripts/check_arch.py  扫描 Python import，违反第 2 节规则即失败
  scripts/check_js.py    单独语法检查 + 三个文件合并后再检查一次
                         （能抓到跨文件重复定义这类历史 bug）
  两者都接进 make test（arch → 单元测试）
```

## 8. 明确不做

```text
· 不引入前端框架（React/Vue）——收益低于成本
· 不改数据模型（歌单 / 读音 / offset 已稳定）
· 不再拆 lyrics（已经三层，够用）
· 不把引擎做成服务（保持进程内调用，简单）
```
