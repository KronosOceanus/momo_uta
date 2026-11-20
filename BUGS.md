# BUG 记录

> 记录用户实际遇到、尚未修复的问题。
> 每条包含：现象、复现、根因判断、影响、修复方向、状态。

## BUG-001 导入后 2–3 秒内点歌没有反应

- **状态**：待修
- **记录时间**：2026-11-20
- **发现场景**：刚导入歌曲后，立刻点击歌单里的歌曲

### 现象

```text
刚导入完（尤其是多首/整个文件夹）后，
立刻点击列表里的歌曲，界面没有反应；
大约等 2–3 秒，再点才正常。
```

```text
可能是所有歌都慢，也可能只有新导入的歌慢；
目前没有区分，先按“导入后的短暂无响应”记录。
```

### 复现

```text
1. 歌单右键 → 导入音乐，选择多首音频
2. 导入完成、列表刚刷新
3. 立刻单击列表里的任意歌曲
4. 界面不变，2–3 秒后才响应/才显示歌词
```

### 根因判断（待验证）

```text
主因：导入接口同步做了全库重扫。

import_to_list：
  → 保存 imports.json
  → LIB.refresh()            // 没有 uid 参数 = 全库 scan_library
  → 返回 lists

LIB.refresh() 内部：
  scan_library()
    遍历 music_dirs + imports.json
    每首走 _entry / 指纹 / 歌词缓存
  CACHE.clear()
  CACHE.update()

1400 首规模约 2–3 秒；
扫库线程占着 GIL，其他 HTTP 请求（点歌的 /api/song）会排队。
```

```text
放大问题：
  load(i) 是先 await /api/song/<idx>，拿到载荷才改界面。
  这 2–3 秒里没有 loading 占位，点击看起来完全没反应。
```

```text
新导入的歌还多一层：
  refresh 完成前它们不在 CACHE；
  如果点的是旧列表里的旧 idx，可能拿到旧数据或 404。
```

### 影响

```text
· 导入后短暂“点了没反应”，容易被当成卡死
· 用户会重复点击，可能触发多次 load
· 新导入的歌在 refresh 完成前不可用
```

### 修复方向

```text
1. 导入改增量刷新
   新导入的路径已知，只对这几个文件建 _entry 并插入 CACHE，
   不调用全库 scan_library。

2. 前端点击立即给反馈
   load 开始就先显示“载入中…”或置灰列表，
   请求回来再渲染。

3. 导入接口尽快返回
   列表更新与全量扫描解耦；扫描只作为后台兜底。

4. 验证
   记录 /api/pl import 与紧接着 /api/song 的耗时；
   对比增量刷新前后。
```

### 相关代码

```text
src/nihonco_player/service/playlist.py   import_to_list
src/nihonco_player/core/library.py       refresh / scan_library
src/nihonco_player/static/10-app.js      doImport / load
```

## 记录模板

```text
## BUG-XXX 标题

- 状态：待修 / 修复中 / 已修
- 记录时间：
- 发现场景：

### 现象

### 复现

### 根因判断

### 影响

### 修复方向

### 相关代码
```
