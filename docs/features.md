# 功能边界与流程图

> 这份文档回答两件事：**这个软件负责什么**、**每个功能内部怎么走**。
> 架构分层见 [`architecture.md`](architecture.md)，播放器手册见 [`player.md`](player.md)。

## 0. 软件是什么

```text
一个本地桌面工具，做两件事：
  ① 日语歌词练习：读歌词 → 注音/罗马音/键盘 → 跟唱、跳句、循环、变调速度不变
  ② 歌词打轴：在波形上打时间戳 → 存成 .lrc → 播放器立刻用它

它不是什么：
  · 不是在线服务（不监听外网、无账号、无云同步）
  · 不是音乐库管理器（不下载音乐、不改标签、不整理目录）
  · 不是 DAW（不剪辑音频、不做淡入淡出、不做多轨）
  · 不是自动打轴（没有 Whisper / 强制对齐；时间轴靠手点）
```

## 1. 全局结构

```text
┌─────────────────────────────── 本机 ───────────────────────────────┐
│  nihonco_player_app（窗口）                                        │
│    ├─ HTTP 服务 127.0.0.1:<随机端口>                               │
│    │    ├─ /            页面                                        │
│    │    ├─ /api/*       数据与动作                                  │
│    │    ├─ /audio/<idx> 音频（支持 Range）                          │
│    │    └─ /static/*    js/css                                      │
│    └─ WebView（WKWebView）                                          │
│         ├─ 05-audio.js   WebAudio 播放引擎（整首解码）              │
│         ├─ 10-app.js     列表 / 载入 / 波形 / 右侧面板               │
│         ├─ 20-editor.js  LRC 表格与保存                              │
│         └─ 30-playback.js 时间语义 / 播放条 / 键盘                   │
│                                                                     │
│  外部依赖：ffmpeg（波形）、mutagen（时长）、pywebview（窗口）        │
│  外部世界：仅访问网易云 / MusicBrainz / lrclib 抓歌词（可离线）      │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. 启动

```text
make app
  → 扫描音乐目录（config: music_dirs + data/curated/imports.json）
  → 建 CACHE{idx → 条目}
  → 起 HTTP（随机端口）
  → 开窗口 → 页面加载 → 三个 JS 模块初始化
  → 前端 GET /api/pl → 渲染歌单树
  → 默认不自动播放；日志写入 data/cache/app.log
```

## 3. 歌单

```text
默认歌单（default）：锁定 —— 不可删除、不可改名；可清空、可导入
自建歌单：可新建 / 改名 / 清空 / 删除
一个歌单 = 一串 uid（md5(音频绝对路径)[:12]）；同一首歌可在多个歌单

【新建歌单】→ prompt 名称 → POST /api/pl {list_create}
【右键歌单】→ 菜单：导入音乐 / 重命名 / 清空 / 删除
     ├─ 重命名 → list_rename（default 拒绝）
     ├─ 清空   → list_clear
     └─ 删除   → list_delete（default 无此菜单项）
【拖动条目】→ 拖到别的歌单 → entry_move
【条目 ✕】  → entry_remove（歌本身不删）
【展开/收起】→ ui_open（写盘，下次打开保持）
```

## 4. 加载一首歌

```text
点列表项（单击载入，双击载入并播放）
  → load(idx)
      ├─ 若正在 LRC 编辑且有改动：先锁定编辑 + 保存（失败则中止）
      ├─ GET /api/song/<idx>
      ├─ 换歌 → 两个编辑模式都关闭
      ├─ 载荷 pending？
      │    ├─ 是（没歌词）
      │    │    ├─ 立即绑定音频（commitAudio）→ 可播放
      │    │    ├─ 后台触发匹配：POST /api/pl {match}
      │    │    └─ 轮询 /api/song：匹配到 → 重新 load（界面换成有歌词）
      │    └─ 否
      │         ├─ 渲染左侧歌词（注音 HTML）
      │         ├─ 渲染右侧罗马音/键位
      │         ├─ 恢复手改读音（restoreEdits）
      │         └─ 读取 offset、同步模式、预载音频
      └─ 返回成功/失败（失败保留当前歌）
```

## 5. 播放与跳转

```text
播放引擎（05-audio.js）：
  src 变化 → fetch /audio/<idx> → decodeAudioData → 整首 PCM 在内存
  play()   → AudioBufferSourceNode.start(0, offset)
  seek(t)  → stop 旧 source → 新建 source.start(0, t)   ← 采样级，无解码器 flush
  currentTime 由 AudioContext 时钟推算；timeupdate 20Hz

跳转（点行 / 上一句 / 下一句 / ±10 秒 / 点波形）：
  seekPrecise(t)
    ① 若在播：pause()（旧声音与画面立即停）
    ② 若未解码：await preload()
    ③ 设 currentTime = t，立刻刷新进度条
    ④ 等 seeked / canplay
    ⑤ 原来在播 → 继续播；原来暂停 → 保持暂停
  （连点合并：序号机制，最后一次生效）

单句循环：
  锚定开启时所在行 → 播到下一行起点 → 回到本行起点
速度：
  playbackRate 改变会在切换前结算位置，再按新速率推进
```

## 6. 整体偏移

```text
只影响"播放对齐"，不改 .lrc
  [−0.5][−0.1] 0.00 [+0.1][+0.5]
    → POST /api/pl {ui_offset} → data/curated/song_meta.json
    → 立即重算当前行并重绘（暂停时也生效）
头部 chip「偏移 +0.30s」→ 点击清零
```

## 7. 重新匹配歌词

```text
点【重新匹配歌词】
  → 若在 LRC 编辑：先退出（保存失败则中止）
  → POST /api/rematch（候选完全来自网络，不读缓存当候选）
       ├─ 网易云搜索 + MusicBrainz 规范化
       ├─ 过滤：名字匹配、时长差、排除词
       └─ 若当前 id 也在结果中 → 标 ●，并标「本地已修改」（文本对比）
  → 弹候选菜单 → 点一条
       ├─ 若是"本地已修改"那条当前项 → 确认"用网上原版覆盖？"
       └─ POST /api/pick {id} → 按 id 抓文本 → 覆盖缓存（首次备份 .bak）→ 重载本曲
```

## 8. 振假名编辑（模式一）

```text
开【振假名编辑模式】
  → 歌词区变成"可点词语"（A/AB 档可改，B 档给候选）
  → 点词 → 候选/输入假名 → POST /api/line {line,start,reading}
  → 写 data/curated/readings.json（按歌 + 行 + 位置）
  → 该行即时重绘（罗马音/键位同步）
  → 【全部重置】→ edit_clear → 删掉这首歌的全部手改
互斥：开此模式会关闭 LRC 模式；切歌两者都关
```

## 9. LRC 编辑（模式二）

```text
开【LRC 编辑模式】
  → GET /api/lrc {load}
       ├─ 有 .lrc：按文件顺序解析（保留未打点草稿行；元数据单独存）
       └─ 没有：退回歌词缓存（首次保存会生成文件）
  → 渲染表格（行号 │ 时间戳 │ 文本），右侧罗马音隐藏
  → 显示波形（ffmpeg → 20ms 峰值 → data/cache/wave）

打点：
  点波形 → 设播放位置 + 标记
  点行   → 音频跳到该行；【↤】把标记写进该行
  Enter（非输入框）→ 在选中行后加一行
  行首 Backspace → 与上一行合并
  多选：Ctrl 点选 / Shift 区间 / Shift 拖拽框选
  ⌘A 全选、Delete 删行、⌘V 粘贴多行（支持 [mm:ss.xx] 前缀）

保存：
  改动 → markDirty（未保存…）→ 停手 1.5 秒自动保存
  【保存】总是写一次
  POST /api/lrc {save, lines}
      → core/lrcio.save：
          首次 → 备份 .lrc.bak
          保留原文件里的元数据标签（按 before 位置插回）
          未打点的行写成纯文本（不补 00:00.00）
          同步歌词缓存 → 播放器立刻生效

其他：
  【导入LRC文件】→ 选外部 .lrc → 确认 → 覆盖（首次备份）→ 重载表格
  【恢复最初】   → 用 .lrc.bak 覆盖 → 重载
  【另存为】     → 原生保存对话框（不动原文件）

切换期间：锁定编辑（inert）+ 先保存再切；保存失败留在原地
```

## 9.5 人声分离

```text
点开一首歌
  → 前端 POST /api/vocals {idx}（幂等）
  → 服务端查 data/cache/vocals/<uid>/meta.json
       ├─ 有：直接返回 done
       └─ 无：进队列（单线程串行），立即返回 queued
  → 前端每 1.5 秒轮询状态：
       queued → running → done / failed
  → done 后：
       · 顶栏显示「有人声」或「纯音乐」
       · 若在 LRC 模式 → 重新拉波形（src=vocals）
       · 若是没有歌词的歌 → 有人声才继续匹配歌词
```

```text
分离过程（后台）：demucs --two-stems=vocals → vocals.wav
                   → ffmpeg 转 16k 单声道
                   → 20ms RMS 统计（ratio / floor / threshold）
                   → 写 meta.json
```

## 10. 导入音频

```text
右键歌单 → 导入音乐… → 原生选择器（文件/文件夹都可）
  → POST /api/pl {import, list, paths}
      ├─ 递归找音频（mp3/flac/wav/m4a/aac/ogg）与 .lrc
      ├─ 音频 + 同名 lrc → 写歌词缓存（跳过联网）
      ├─ 只有音频 → 也进歌单；打开时懒匹配
      ├─ 只有 lrc → 尝试找同目录同主干音频
      └─ 登记 data/curated/imports.json（不在音乐目录也能列出来）
  → 重新扫库 → 按路径算 uid 入歌单 → 返回统计（新增/待匹配/未配对）
```

## 11. 标注管线（引擎）

```text
歌词一行
  → nihonco_yomi.Annotator
      ├─ Sudachi 分词
      ├─ 4 张表 + 规则链 → 读音候选
      ├─ 语料频次定档：A / AB / B / C
      └─ 不变量校验（违反 → 弃权 B）
  → render：ruby HTML / 罗马音 / 键位（同一份 span 数据）
  → 前端叠加手改读音（readings.json）
```

## 12. 数据文件

```text
用户资产（不可重建）
  data/curated/playlists.json   歌单、成员、展开状态
  data/curated/readings.json    手改读音
  data/curated/song_meta.json   每首 offset
  data/curated/song_tags.json   ♪ / 语 / ✗ 标记（只作标记，不隐藏）
  <音频同目录>/*.lrc  *.lrc.bak  歌词文件与首次备份

可重建
  data/cache/lyrics/*.json      歌词缓存（含来源 id）
  data/cache/wave/*.json        波形峰值
  data/cache/app.log            运行日志
```

## 13. 状态与不变量

```text
模式：普通 / 振假名编辑 / LRC 编辑 —— 三者互斥（开一个关另一个）
切歌：两个编辑模式都关闭；LRC 模式下有改动先保存
LRC 切换：锁定编辑 → 保存 → 解锁（失败则留在原地）
播放语义（两种视图共用）：
    生效时间 = 行时间 + offset
    当前行 = 最后一个"生效时间 ≤ 播放时间"的非 meta 行
    meta 行（作词/作曲/…）不参与跳句与打点
播放状态：SET 在 commitAudio，切歌只切 src，不主动停旧（直到用户播放/跳转）
```

## 14. 失败路径

```text
音频读不出 / 解码失败 → 播放条不动，提示由引擎 error 事件吞掉（待改进）
歌词抓不到        → 显示"没匹配到歌词（仍可播放）"
保存失败          → 提示"歌词保存失败，当前编辑已保留"；不切换
首次保存          → 自动生成 .lrc.bak；没有 .bak 时【恢复最初】提示无备份
只读目录          → 保存失败 → 建议【另存为】
```

## 15. 明确不做（边界）

```text
· 不改音频文件本身（不剪辑、不转码、不写标签）
· 不自动打轴、不做人声分离（波形目前是原曲）
· 不管理音乐库（不下载、不删除音频、不移动文件）
· 不做多用户 / 网络共享 / 移动端
· 不做歌词翻译（歌词里的中文行按原文显示）
```
