# BUG 记录

## BUG-001 导入后 2–3 秒内点歌无响应

- 状态：待修
- 日期：2026-11-20
- 现象：刚导入歌曲后，立刻点列表里的歌，界面 2–3 秒没反应。
- 原因：`import_to_list` 同步执行 `LIB.refresh()` 全库扫库，占着 GIL；前端 `load()` 等待 `/api/song` 期间也没有载入提示。
- 修复方向：导入只增量刷新新增歌曲；前端点歌先显示“载入中…”。
- 相关：`service/playlist.py` 的 `import_to_list`、`core/library.py` 的 `refresh/scan_library`、`static/10-app.js` 的 `load`。
