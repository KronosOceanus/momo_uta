# 歌词练习播放器（桌面应用）

> 代码在 `nihonco_player/`（服务 + 前端）与 `nihonco_player_app/`（窗口壳）。
> 这份文档描述**当前已实现的行为**；LRC 打轴部分见 [`lrc-editor.md`](lrc-editor.md)。

## 1. 怎么启动

```bash
make app        # 唯一入口：随机端口起服务 + 原生窗口
```

```text
没有浏览器模式：页面与静态资源由 app 内置服务提供
依赖：pywebview（窗口）、ffmpeg（波形）、mutagen（时长）
```

## 2. 模块

| 文件 | 行数 | 职责 |
|---|---|---|
| `http/routes.py` | 159 | 路由表 + handler（只转发） |
| `http/static.py` | 44 | 静态文件与音频流（Range） |
| `http/server.py` | 22 | 起服务 |
| `service/song.py` | 220 | 载荷装配、改读音、重新匹配、选候选 |
| `service/playlist.py` | 101 | 歌单动作、导入、打标 |
| `service/lrc.py` | 45 | LRC 加载/保存/备份/恢复/导入 |
| `static/10-app.js` | 365 | 状态、工具、歌单、载入单曲、右侧面板 |
| `static/20-editor.js` | 509 | LRC 编辑表格 |
| `static/30-playback.js` | 244 | 时间语义、播放条、波形跟随、键盘 |
| `static/player.css` | 227 | 深色主题样式 |
| `static/player.html` | 59 | 页面骨架 |
| `playlists.py` | 184 | 歌单（uid 集合 + 文件锁） |
| `library.py` | 100 | 扫目录、读缓存、导入索引 |
| `importing.py` | 150 | 导入：目录递归 / 音频+lrc / 纯音频 / 纯 lrc |
| `lyrics*.py` | 498 | 歌词：文本解析 / 缓存 / 抓取匹配（三层 + 门面） |
| `lrcio.py` | 146 | `.lrc` 读写、备份、恢复、JSON 歌词格式兼容 |
| `waveform.py` | 76 | ffmpeg 解码 → 20ms 峰值 → 缓存 |
| `edits.py` | 66 | 手改读音（按歌存储） |
| `song_meta.py` | 54 | 每首歌的 offset |
| `web.py` | 19 | 页面装配（注入配置） |
| `nihonco_player_app/__main__.py` | 104 | 窗口 + 原生对话框（选目录/文件/lrc/另存为） |

## 3. 歌单

```text
default  「默认歌单」：锁定 —— 不能删、不能改名，可以清空、可以导入
user     自建歌单：能改名、能删、能清空
```

```text
一个歌单 = 一串 uid（md5(音频绝对路径)）
同一首歌可以同时出现在多个歌单
歌单内条目可拖到别的歌单（移动）、可拖拽排序？—— 当前只有"移出/移入"，行内排序未做
```

```text
顶部    [＋ 新建歌单]
每行    ▾ 名称  数量        ← 右键弹出菜单：导入音乐 / 重命名 / 清空歌单 / 删除歌单
条目    单击载入 / 双击播放 / 悬停 ✕ 从歌单移除 / 右侧 ♪ 语 ✗ 打标
标签    ♪=inst 语=非日文 ✗=标错，只作标记，**不再隐藏歌曲**
搜索    跨歌单过滤，命中时自动展开
```

## 4. 播放

```text
自绘播放条    ⟲10  ▶/⏸  10⟳   已播 ▬▬●▬▬ 总长   🔊 音量
              进度条上叠"每句一个刻度点"
播放语义（两种模式共用一套）
  生效时间 = 行时间 + 整体偏移
  当前行 = 最后一个"生效时间 ≤ 播放时间"的非 meta 行
  点击行 / 右侧罗马音   → 跳到该行时间（在播就继续播）
  上一句 / 下一句       → 在非 meta 行序列里前后移动
  单句循环              → 锚定开循环时所在行，跨下一行起点就回跳
```

```text
meta 行（作词/作曲/编曲/演唱…）不参与打点与跳句，但仍显示
```

## 5. 整体偏移

```text
位置    LRC 工具行第三行左侧：[−0.5][−0.1] 0.00s [+0.1][+0.5]
作用    只平移播放对齐，不改文件
存储    data/curated/song_meta.json（每首歌一个值）
提示    偏移 ≠ 0 时头部显示「偏移 +0.30s」，点一下清零
```

## 6. 界面结构

```text
第 1 行  【开始】歌名                          振假名编辑模式 / LRC 编辑模式
第 2 行  【全选】【加行】【删行】   【保存】【另存为】【导入LRC文件】【恢复最初】
第 3 行  整体偏移 …                                                     跟随：开
第 4 行  波形（仅 LRC 模式）
主区     左：歌词 / 编辑表格        右：罗马音 or 键位（LRC 模式隐藏）
底部     上一句 / 播放 / 下一句 / 单句循环 / 重新匹配歌词 / 速度
         自绘播放条
```

## 7. 两种编辑模式（互斥）

```text
振假名编辑模式  点词语改读音（A/AB/B/C 四档，B 有候选）
LRC 编辑模式    见 lrc-editor.md：波形、时间轴、保存、导入
切歌时两个模式都自动关闭
```

## 8. 歌词来源

```text
抓取    网易云（主）→ MusicBrainz 规范化 → lrclib（兜底）
缓存    data/cache/lyrics/<md5(歌名|歌手)>.json（命中不联网）
本地    .lrc 文件（有就优先，LRC 编辑器保存后也写它）
懒匹配  没有歌词的歌点开时才抓，右侧显示「匹配歌词中…」
```

## 9. 数据文件

| 文件 | 内容 |
|---|---|
| `data/curated/playlists.json` | 歌单、成员、列表顺序、展开状态 |
| `data/curated/song_meta.json` | 每首歌的 offset |
| `data/curated/readings.json` | 手改的振假名 |
| `data/curated/song_tags.json` | ♪ 语 ✗ 标记 |
| `data/curated/imports.json` | 导入过的音频路径 |
| `data/cache/lyrics/` | 歌词缓存 |
| `data/cache/wave/` | 波形峰值缓存 |

```text
playlists / song_meta / readings / edits 的写入都加了 fcntl 文件锁
```

## 10. 接口

```text
GET  /                    页面
GET  /static/*            css/js
GET  /api/pl              歌单树 {lists, open}
GET  /api/library         扁平歌曲列表（含 tags）
GET  /api/song/<idx>      单曲（注音 + 罗马音 + edits + offset）
GET  /audio/<idx>         音频（支持 Range）
GET  /api/wave/<idx>      波形峰值
POST /api/pl              歌单动作：list_create/rename/delete/clear/reorder,
                          entry_move/remove/reorder, ui_offset, edit_clear, import
POST /api/line            改一处读音（写 readings）
POST /api/apply           批量恢复读音
POST /api/rematch         重新匹配候选
POST /api/pick            选定候选（写缓存）
POST /api/tag             打标/取消
POST /api/import/one      导入（扫描 + 落库 + 归入歌单）
POST /api/lrc             load / save / backup / restore / import_lrc
```

## 11. 已知问题

```text
· 歌单改名、行内拖动排序没做界面入口
· 波形用人声之前，只能看到原始混音波形（人声分离未接）
· 打点只能"点波形 → 点 ↤"，没有键盘打点
· 歌词覆盖不足整首时只给一个 ⚠ 提示，不阻断
```
