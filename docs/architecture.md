# 架构

> 读者：要加功能、改数据流、判断"这段代码该放哪"的人。
> 定位：分层、目录、边界规则、一次请求怎么走。
> 自成一体：不依赖其它文档；具体的格式/算法细节由各模块文档展开。

## 0. 三十秒版本

```text
桌面应用 = pywebview 窗口 + 本机 HTTP 服务

请求方向：
  前端（window.NH） → HTTP（routes） → service（编排） → core（数据/规则）
                                                        ↘ nihonco_yomi（纯计算）

依赖只能向下，不能反向。
scripts/check_arch.py 用 AST 检查，`make test` 会跑。
```

```text
五个包：
  nihonco_yomi        纯计算：注音、罗马音、词表、不变式
  nihonco_player.core 数据与规则：曲库、歌词、指纹、歌单、人声、波形
  nihonco_player.service 编排：单曲、LRC、歌单
  nihonco_player.http 协议：路由、静态文件、音频流
  nihonco_player_app  桌面壳：起服务、开窗口、文件对话框
```

## 1. 目标与边界

```text
是什么：
  · 本地优先的日语歌词练习播放器
  · 一个进程、一个窗口、一个本机端口
  · 数据在 data/；歌词标注是用户资产

不是什么：
  · 不是多用户服务（没有登录、没有数据库、没有远程 API 暴露）
  · 不是前端框架项目（没有打包器，五个 classic script）
  · 不是流式音频服务（整首解码进内存）
```

```text
三条设计约束：
① 纯计算与 IO 分开
   引擎不知道文件、网络、HTTP；core 不知道 HTTP；service 不知道窗口
② 数据有单一归属
   曲库/歌词/歌单/人声/波形各自有明确的读写模块
③ 前端只有一个全局
   window.NH；五个脚本按顺序加载，共享这个命名空间
```

## 2. 分层与依赖规则

```text
┌──────────────────────────────┐
│ nihonco_player_app（桌面壳）  │  webview、文件对话框、日志
└──────────────┬───────────────┘
               │ 调用
┌──────────────▼───────────────┐
│ nihonco_player.http           │  路由、静态文件、Range
└──────────────┬───────────────┘
               │ 调用
┌──────────────▼───────────────┐
│ nihonco_player.service        │  song / lrc / playlist
└──────────────┬───────────────┘
               │ 调用
┌──────────────▼───────────────┐
│ nihonco_player.core           │  数据、文件、网络、缓存
└──────────────┬───────────────┘
               │ 调用
┌──────────────▼───────────────┐
│ nihonco_yomi                  │  纯计算，无 IO
└──────────────────────────────┘
```

```text
硬规则（check_arch.py）：
  1. nihonco_yomi 不能 import 任何 nihonco_player*
  2. core 不能 import service / http
  3. service 不能 import http
  4. http 不能 import nihonco_player_app
```

```text
违反时：make test 直接失败，输出"哪一行 import 了谁"。
目的不是洁癖，而是保证：
  · 引擎可以单独跑评测/命令行
  · core 可以在没有服务端的情况下被测试
  · service 可以被脚本直接调用
```

## 3. 目录

```text
src/
├── nihonco_yomi/               纯计算
│   ├── annotate.py             分词 → 片段 → 档位
│   ├── kana.py                 假名/汉字判定
│   ├── romaji.py               罗马音
│   ├── render.py               键位/展示
│   ├── invariants.py           I1–I8 不变式
│   ├── counters.py             覆盖率/档位统计
│   ├── llm.py                  LLM 辅助（可选）
│   ├── thresholds.py           设计阈值（A 类）
│   ├── config.py              运行参数（B 类）
│   ├── paths.py                路径常量
│   ├── common.py               共享小工具
│   └── serve.py                引擎命令行
│
├── nihonco_player/
│   ├── core/                   数据与规则
│   │   ├── library.py          扫库、CACHE、refresh、标签
│   │   ├── lyrics.py           歌词门面（fetch/cache/text 的聚合）
│   │   ├── lyrics_fetch.py     网易云候选 / 过滤 / 抓取
│   │   ├── lyrics_text.py      名称/语言/打分/排除
│   │   ├── lyrics_cache.py     歌词缓存读写
│   │   ├── lrc_doc.py          LRC/nhlrc 格式（纯函数）
│   │   ├── lrc_files.py        data/lyrics 读写、备份
│   │   ├── annotation.py       行 → seg、对齐、渲染
│   │   ├── fingerprint.py      音频指纹 + 索引
│   │   ├── song_meta.py        整体偏移/标签元数据
│   │   ├── playlists.py        歌单文件
│   │   ├── importing.py        导入配对
│   │   ├── vocals.py           demucs 队列 + VAD
│   │   ├── waveform.py         峰值
│   │   └── diag.py             诊断日志（含 traceback）
│   │
│   ├── service/                编排
│   │   ├── song.py             载荷、改读音、匹配、选候选
│   │   ├── lrc.py              编辑模式读写、导入导出、备份
│   │   └── playlist.py         歌单增删改、导入、打标
│   │
│   ├── http/
│   │   ├── routes.py           路由与参数校验
│   │   ├── server.py           ThreadingHTTPServer
│   │   └── static.py           静态文件 + Range
│   │
│   ├── static/                 前端（无构建）
│   │   ├── player.html
│   │   ├── player.css
│   │   ├── 05-audio.js         音频引擎
│   │   ├── 06-state.js         查看歌曲的加载/匹配状态机
│   │   ├── 10-app.js           状态/载入/波形/人声/提示
│   │   ├── 20-editor.js        LRC 打轴
│   │   └── 30-playback.js      时间语义/播放条/高亮
│   │
│   └── web.py                  页面装配 + 注入 __CFG
│
├── nihonco_player_app/         桌面壳
│   ├── __main__.py             起服务、开窗口、文件对话框
│   └── logsetup.py             日志文件/异常钩子
│
config/defaults.json            仓库默认运行参数
data/                           运行数据（见 §10）
docs/                           文档
scripts/check_arch.py           分层检查
scripts/check_js.py             前端完整性检查
tests/                          Python + Node 测试
tools/                          建表/评测/演示
```

## 4. 引擎层 `nihonco_yomi`

```text
输入：日文歌词行（字符串）
输出：片段序列 [{base, ruby, level}]、罗马音、键位、覆盖率

不碰：
  · 文件系统（除了 paths 常量）
  · 网络
  · 曲库/歌单/HTTP

所以它可以：
  · 在命令行单独跑（serve.py）
  · 在评测里批量跑（eval/）
  · 在 core 里被 annotation.py 调用
```

```text
两类参数要分清：

A 类：设计阈值
  位置：nihonco_yomi/thresholds.py
  例子：MIN_CORPUS_N、SINGLE_READING_SHARE、语料统计下限
  含义：决定 A/AB/B 的切法
  改了必须重跑 make stats 和三套评测

B 类：运行参数
  位置：config/defaults.json + data/config.json
  例子：时长差、搜索上限、人声队列/执行超时、波形采样率、窗口尺寸
  含义：不改判定规则，只调行为
  改了重启（或刷新页面）生效

paths.py 只放路径常量，不放逻辑。
```

## 5. `core`：数据与规则

### 5.1 模块分组

```text
曲库
  library.py      扫目录、条目、CACHE、标签
  fingerprint.py  音频身份（uid）
  song_meta.py    整体偏移、展示用元数据

歌词来源
  lyrics.py       门面：fetch + cache + text 的聚合
  lyrics_fetch.py 网易云候选 / 过滤 / 抓取
  jobs.py         统一任务表（vocals/match/rebuild）
  lyrics_text.py  名称归一、语言、打分、排除
  lyrics_cache.py 缓存文件

歌词文件
  lrc_doc.py      纯格式：解析/渲染/校验/对齐
  lrc_files.py    data/lyrics 路径、读写、备份
  annotation.py   行文本 → seg（调用引擎）

播放器数据
  playlists.py    歌单 JSON
  importing.py    文件配对
  vocals.py       人声分离队列
  waveform.py     波形峰值
  diag.py         诊断日志（log / exception）
```

```text
core 的特点：
  · 可以直接被脚本/测试调用，不需要 HTTP
  · 不返回 HTML；只返回数据/路径/状态
  · 文件写入集中在少数模块（lrc_files / playlists / cache / meta）
```

### 5.2 曲库与 `CACHE`

```text
CACHE：idx(str) → 条目（只负责列表顺序）
BY_UID：uid → 同一份条目（唯一歌曲身份）
  条目字段：
    key       md5(文件名主干)[:12]        用于标签/偏移等"按歌"的元数据
    uid       音频指纹                    用于歌词/歌单/人声
    file      绝对路径
    stem      文件名主干
    title/artist/orig
    has_lyric 是否有可用歌词（nhlrc 优先，其次缓存；网络歌词需时间轴）
    source/lang/suspect
    group     所在目录

idx 是"当前会话里的位置"：
  每次全量扫库都可能变；不能持久化，不能当身份。

发布：
  _publish() 构建新 idx 表 + BY_UID；
  加锁 update + 删除旧 key，不先 clear。

读/写接口只用 LIB.resolve(uid)：
  只查 BY_UID；idx 不是身份。
```

```text
refresh(uid)：
  uid 在 CACHE 里 → 只重算这一条（不扫全库、序号不变）
  uid 不在 → 尝试索引/imports 补一条；找不到不扫全库

重建/启动加载：
  _publish() 一次性发布新 CACHE + BY_UID
  并发读不会看到 clear 后的空表

refresh 与同内容副本：
  某个路径内容变了，先更新该条；
  如果 CACHE 里还有别的副本持有旧 uid，
  BY_UID[旧 uid] 继续指向剩余副本；
  选择剩余副本前要 force 重算指纹，
  文件不存在或指纹不匹配的副本不能使用；
  没有 live 副本才移除旧 uid。

歌词文档状态：
  nhlrc 有正文 → 显示本地歌词
  nhlrc disabled=true → 显示无歌词，跳过缓存和自动匹配
  没有 nhlrc → 可读网络缓存或触发自动匹配
  delete 写 disabled；save/import/pick/restore 重新启用。

load_for_playlists()（启动用）：
  读 playlists.json 的所有成员 uid
  用指纹索引 / library_index.json 反查 uid → 路径
  只加载歌单引用到的 imports，不加载无关 imports
  只对这些路径建 CACHE；不递归 music_dirs
  缺失 uid 只记入 LAST_MISSING，不在此处全量扫

自动重建：
  启动后前端看到 auto_rebuild（有缺失）→ 空闲 8 秒后
  POST /api/pl {action:"library_rebuild"}
  → scan_library() 全量扫一次 + 裁剪索引
  → 记录 last_missing / last_rebuild / last_recovered
  → 同一缺失集合且上次没找回，不再自动重试

scan_library()：
  按 music_dirs 递归；扩展名来自 library.extensions
  + data/curated/imports.json 里登记的导入文件
  用指纹索引避免每次重算
  全量扫描后裁剪 library_index / fingerprints 的失效路径
  仍用于测试、显式全量重建和自动重建
```

### 5.3 三个 id 不要混

```text
uid    音频指纹：所有读写/播放/任务的主身份
idx    纯展示位置：列表 data-i、排序
key    md5(文件名主干)：标签、整体偏移等按歌元数据
```

```text
所有歌曲接口只传 uid：
  /api/song/<uid>
  /api/wave/<uid>
  /audio/<uid>
  /api/lrc、/api/line、/api/rematch、/api/pick、/api/jobs 用 body.uid

idx 只用于列表显示和 DOM；
任何读写都不接受 idx。
```

```text
一个常见错误：把 idx 写进歌单。
idx 每次启动都可能变；歌单只存 uid。
```

## 6. `service`：编排

```text
service 只做"把 core 的步骤串起来"，不实现具体规则：
  · 读哪个文件、调用哪个 core 函数、按什么顺序
  · 返回前端要的载荷/结果
  · 不解析 HTTP，不碰窗口
```

### 6.1 song

```text
song_payload(uid)
  曲库条目 → 歌词（data/lyrics 或缓存）→ 内存逐行注音（不写 nhlrc）
  → {uid, idx, title, artist, lines, offset, audio, pending?}

edit_line_action(req)  // req.uid 优先
  改一处读音 → 重算该行 → 立即写 nhlrc → 返回新 ruby/rm/ky

rematch(uid, duration)
  候选只来自网络（网易云）→ 返回前 10

pick(uid, id)
  网络歌词重写当前 nhlrc 正文（备份、读音重来）

lazy_match(item)
  强制联网取歌词 → 只写歌词缓存 → 刷新曲库；disabled 时跳过
```

### 6.2 lrc

```text
lrc_action(req)：
  load      读当前歌词（rows + metadata）
  save      锁内读改写 + version 校验 + 备份 + 原子写 nhlrc
  backup    查 .bak 是否存在/时间/行数
  restore   version 校验后用 .bak 原子覆盖（重新启用）
  export    生成 nhlrc 与纯 lrc 两种文本
  import_lrc 直接原子写 nhlrc（重新启用）
  delete    原子写 disabled nhlrc；保留 .bak，可恢复
```

### 6.3 playlist

```text
playlists_action(req)：
  list_create / list_rename / list_delete / list_clear
  entry_remove / entry_move / entries_move / entry_reorder / list_reorder
  ui_open / ui_offset
  match（懒匹配）
  ui_offset/edit_clear/match 找不到 uid 时返回 ok:false，
  不能静默成功
  edit_clear（清空标注，恢复默认）
  import（导入音频/歌词，走 import_to_list）

```

```text
所有 action 都是"一个 req dict 进、一个 dict 出"，
方便 HTTP 和脚本共用。
```

## 7. `http`：协议层

```text
routes.py 只做三件事：
  ① 解析路径/JSON
  ② 校验必填字段（缺失 400）
  ③ 转发给 service，JSON 返回
```

### 7.1 路由

```text
GET
  /                       页面（注入 __CFG）
  /static/*               前端静态文件
  /api/song/<uid>         单曲载荷
  /api/pl、/api/playlists  歌单列表
  /api/library            曲库列表 + uid
  /api/wave/<uid>[?src=vocals]  波形峰值
  /api/jobs/<id>          统一任务状态
  /api/jobs/active        当前活动 vocals 任务
  /audio/<uid>            音频流（Range）

POST
  /api/pl                 playlists_action
  /api/playlist           同上（别名）
  /api/line               改一处读音
  /api/rematch            重新匹配候选
  /api/pick               选中候选
  /api/import/one         导入
  /api/lrc                LRC 编辑（uid）
  /api/jobs               启动 vocals / match / rebuild 任务
  /api/jobs/<id>/cancel   取消单个 vocals 任务
  /api/jobs/cancel_all    取消所有 vocals 任务
  /api/log                前端未捕获错误写 app.log
```

```text
必填字段在 REQUIRED 表里声明：
  缺了直接 400，返回 {"ok":false,"error":"缺少参数：…"}

HTTP 边界：
  handler 抛意外异常 → diag.exception("http", ...) 写 traceback
  → 前端收到 {"ok":false,"error":"内部错误"} 500
  已解析/缺参/业务可预期错误不走这个兜底
  不让 service 里出现 KeyError/None 兜底
```

### 7.2 音频与静态

```text
/audio/<uid>：
  按 uid 解析；支持 Range（206），按 64KB 分块写
  Content-Type 按扩展名映射
  前端 WebAudio 需要整文件 fetch，但 Range 仍保留给浏览器/调试

/static/*：
  只读、防目录穿越、文本按 UTF-8
```

### 7.3 错误约定

```text
HTTP 层：
  400  参数缺失 / 非法 JSON
  404  未知路径 / 未知歌曲 / 音频文件不存在
  200  正常；业务失败用 {"ok":false,"error":"…"} 表达

service 层：
  不抛业务异常给前端；返回 {ok/error} 或 {error}
```

## 8. 桌面壳 `nihonco_player_app`

```text
启动顺序：
  ① logsetup.setup()：日志文件 + sys.excepthook
  ② load_cache_for_playlists() → 只加载歌单成员和被引用的 imports
  ③ make_server(0)：随机端口，只绑 127.0.0.1
  ④ 后台线程 serve_forever
  ⑤ webview.create_window + start
```

```text
窗口里的前端通过 window.pywebview.api 调本机能力：
  pick_any()       一个对话框选文件/文件夹/多个
  pick_folder()    兼容旧接口
  save_text(name, nhlrc, lrc)  导出；.lrc 扩展名写纯 LRC
  pick_lrc_text()  选歌词文件并读文本
```

```text
为什么用随机端口：
  避免固定端口冲突；服务只在本机回环地址。
```

## 9. 前端

```text
没有构建步骤：
  player.html 按顺序加载五个 classic script
  每个脚本是一个 IIFE，只通过 window.NH 暴露
  check_js.py 会检查：
    · 每个文件语法
    · 五个文件拼起来语法（抓跨文件重复定义）
    · 必须是 IIFE
    · 必须取 window.NH
```

```text
分工：
  05-audio.js    AudioEngine：解码、播放、seek、变速、音量
  06-state.js    当前歌曲的加载/匹配纯状态机
  10-app.js      状态、曲库/歌单、载入、波形、人声、toast
  20-editor.js   LRC 表格、打轴、保存、导入导出
  30-playback.js 时间语义、播放条、高亮、循环、键盘

共享状态都在 NH 上：
  NH.S / NH.LINES / NH.WAVE / NH.VIEW / NH.VIEW_MODE …
```

```text
配置注入：
  web.page() 把 config 整个塞进 window.__CFG
  前端只读，不在前端写配置
```

```text
DOM 约定：
  左栏 .ln、右栏 .ln2、编辑表格 .lerow
  状态用 class（.on/.sel/.picked/.dirty）而不是内联样式
```

## 10. 数据布局

```text
data/
├── lyrics/            歌词标注（nhlrc）        进 git（用户资产）
├── vocals/            人声分离结果             不进 git（可重算但贵）
├── cache/             可重建缓存               不进 git
│   ├── lyrics/        歌词抓取缓存
│   ├── wave/          波形峰值
│   ├── fingerprints.json 路径→指纹索引
│   └── app.log
├── curated/           人工/运行维护的数据       进 git
│   ├── playlists.json、song_meta.json
│   ├── imports.json（导入的音频路径）
│   ├── lyrics_exclude.json、counters.json、glossary_lyrics.json
│   └── *.lock         文件锁                   不进 git
├── config.json        本机配置覆盖             不进 git
├── sources/           原始下载                 不进 git
├── corpus/            语料统计                 不进 git
└── tables/            词典机械抽取             不进 git
```

```text
归属原则：
  · 用户资产（歌词/歌单/标签/偏移）→ 进 git，备份有意义
  · 可重建（缓存/波形/人声/语料）→ 不进 git，删了能重算
  · 原始素材（sources）→ 不进 git，体积大
```

## 11. 配置

```text
config/defaults.json   仓库默认值（七组）
data/config.json       本机覆盖（同结构，深层合并）
window.__CFG           注入前端

七组：
  lyrics    匹配与打分 + 搜索上限/超时
  player    播放器通用 + ui 节奏
  waveform  波形
  vocals    人声分离
  library   扫描/导入
  app       桌面壳/日志
  jobs      job 轮询/保留条数；state=生命周期，stage=实际执行阶段
```

```text
优先级：代码里的 _FALLBACK < defaults.json < data/config.json
改 B 类参数：重启（后端）或刷新（纯前端 ui）生效。
A 类阈值不走这里（见 §4）。
```

## 12. 并发与一致性

```text
后端：
  library._LOCK        refresh/扫库串行（RLock）
  lrc_files.LOCK       同一首歌的读-改-写串行（RLock）
  vocals._queue        单线程队列，分离任务串行
  HTTP                ThreadingHTTPServer，每个请求一个线程

前端：
  SAVE_PENDING         同一时刻最多一个保存请求
  LOAD_REQUEST         切歌/载入的旧响应自动作废
  LRC_OPEN_REQUEST     多次进入编辑模式只认最后一次
  SEEK_SEQ             连续跳转只执行最后一次
```

```text
一致性策略：
  · nhlrc 是唯一权威；cache 只做单向回退
  · GET /api/song 不写 nhlrc；自动注音只存在于响应
  · 用户保存/导入/pick/恢复/删除走同一条原子写路径
  · 保存失败保留 dirty；版本冲突不覆盖
  · 写成功但曲库刷新失败时，二者分别报告
```

## 13. 新功能放哪

```text
纯文本→读音/罗马音/档位              nihonco_yomi
读写某个数据文件、调外部命令           core
串多个步骤、组装前端载荷               service
新增 URL/参数校验                     http
窗口/文件对话框/日志                   nihonco_player_app
交互/渲染/播放                          static/*.js
```

```text
判断标准：
  · 需要 HTTP 吗？需要 → http
  · 需要窗口吗？需要 → app
  · 需要多处复用、涉及文件/网络吗？需要 → core
  · 只是编排？→ service
  · 纯计算？→ yomi
```

## 14. 测试与校验

```text
make test =
  scripts/check_arch.py   分层边界
  scripts/check_js.py     前端完整性
  Python unittest         145 条
  node --test             前端逻辑 9 条
```

```text
测试的组织：
  tests/test_lrc_doc / nhlrc / lyrics_store   格式与存储
  tests/test_importing / fingerprint          导入与身份
  tests/test_player_http / playlists_api      接口层
  tests/test_rematch                          匹配
  tests/test_ui_smoke                         真窗口冒烟
  tests/lrc_editor.test.cjs                   前端时间/保存/锁定
```

## 15. 已知取舍

```text
① 单进程、无数据库
   好处：部署简单、数据可 diff；代价：并发能力有限

② 前端无构建
   好处：改完刷新即可；代价：没有类型检查/模块系统，
   只能靠 check_js 和 NH 约定维持

③ 整首音频解码
   好处：seek 采样级精确；代价：内存与首播等待

④ idx 会变
   所有持久化只能用 uid/key，不能用 idx

⑤ 文件即真相
   data/lyrics 与 data/curated 是唯一状态；没有隐藏内存数据库
   好处：可备份/可手改；代价：需要文件锁与串行化
```
