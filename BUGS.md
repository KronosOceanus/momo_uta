# BUG 记录

## BUG-001 导入后 2–3 秒内点歌无响应

- 状态：已修
- 日期：2026-11-20
- 现象：刚导入歌曲后，立刻点列表里的歌，界面 2–3 秒没反应。
- 原因：`import_to_list` 同步执行 `LIB.refresh()` 全库扫库，占着 GIL；前端 `load()` 等待 `/api/song` 期间也没有载入提示。
- 修复：导入改用 `LIB.add_paths` 只加入新增文件，不再全库扫描；已有 idx 不变。
- 相关：`service/playlist.py` 的 `import_to_list`、`core/library.py` 的 `refresh/scan_library`、`static/10-app.js` 的 `load`。

## BUG-002 体感优化（待细化）

- 状态：待修
- 日期：2026-11-20
- 现象：部分操作点击后没有即时反馈，等待感明显；具体场景后续补充。
- 原因：暂未逐项定位，可能与同步扫库、网络匹配、前端无 loading 状态有关。
- 修复方向：统一“点击即反馈”；耗时操作异步化；减少同步全库扫描。
- 相关：`static/10-app.js`、`service/playlist.py`、`core/library.py`。

## BUG-003 LRC 提前匹配

- 状态：待修
- 日期：2026-11-20
- 现象：普通页面还在“分离人声 / 匹配歌词中”，打开 LRC 编辑模式却已经有歌词。
- 原因：LRC 编辑直接读 `data/lyrics` 的 nhlrc 或歌词缓存，不看当前 pending；而普通页面的 `has_lyric` 主要看歌词缓存，两边判断不一致；match 完成与普通页轮询之间也有时间差。
- 修复方向：统一“有没有歌词”的来源；pending 时打开 LRC 要同步/等待；match 完成后主动刷新普通页面。
- 相关：`core/lrc_files.py` 的 `load`、`service/song.py` 的 `song_payload`、`core/library.py` 的 `_entry`、`static/20-editor.js` 的 `openLrcEditor`。
