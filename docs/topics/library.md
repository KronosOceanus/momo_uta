# 曲库、歌单与导入

> 本文说明 CACHE、uid、歌单、导入配对和 offset。
> 身份算法见 [fingerprint](fingerprint.md)，缓存见 [cache](cache.md)。

## 0. 一句话

```text
CACHE = 当前会话的曲库快照
BY_UID = 唯一歌曲身份索引
playlists = uid 列表
imports = 不在 music_dirs 里的音频路径
```

```text
idx 只用于展示。
uid 才是歌曲身份。
```

## 1. 内存模型

```python
CACHE: dict[str, dict]   # idx -> entry
BY_UID: dict[str, dict]  # uid -> entry
```

entry 主要字段：

```text
key / uid / file / stem / orig
group / title / artist / source / lang
has_lyric / suspect
```

```text
CACHE 只代表“本次已加载的曲库”，
不等于 music_dirs 全量。
```

```text
/api/library 读的是 CACHE 快照，不是全盘扫描。
```

## 2. idx / uid / key

```text
uid   音频指纹，身份
idx   展示位置，会变
key   md5(stem)[:12]，历史字段
```

```text
前后端歌曲接口只接受 uid。
idx 不能用于查找、写歌单、写歌词。
```

## 3. 启动加载

```text
load_for_playlists()
  → 收集所有歌单 uid
  → 先用 fingerprints / library_index 找路径
  → 缺失的再从 imports 补
  → _entry 组装
  → publish
  → LAST_MISSING
```

```text
不递归扫描无关目录。
不加载不在歌单里的歌。
```

```text
load_cache_for_playlists()
  = load_for_playlists + _publish
```

## 4. 全量扫描

```text
scan_library(folder=None)
```

```text
遍历 music_dirs
  → 扩展名过滤
  → _entry
  → 去重
  → 附带 imports

全量扫描还会：
  LI.prune(valid)
  FP.prune(valid)
```

```text
显式扫描临时目录不裁剪全局索引。
```

## 5. 组装 entry

```python
_entry(p, group, stored=None, force_fp=False)
```

流程：

```text
LI.get(path)
  → 命中：复用已解析字段
  → 未命中：fingerprint + split_name
  → 查 nhlrc / 歌词缓存判断 has_lyric
  → LI.put
```

```text
force_fp=True：
  强制重算指纹
  用于文件内容变化后刷新 uid
```

```text
has_lyric 是“当前有没有可用歌词”，
不是“有没有 .nhlrc 文件”。
```

## 6. refresh

```text
refresh(uid)
```

```text
uid 已在 CACHE：
  → _entry(force_fp=True)
  → 换 uid 时清理旧 BY_UID
  → 用 _live_copy 找仍在的旧副本

uid 不在 CACHE：
  → 只从已有索引/imports 找
  → 不扫全库
```

```text
保存歌词后 refresh 失败，
不能伪装成歌词没保存。
```

## 7. 自动重建

```text
LAST_MISSING
  最近一次加载没解析到的歌单 uid
```

```text
should_auto_rebuild()
  → 有 missing
  → 且这次 missing 和上次不同
  → 才自动重建
```

```text
rebuild_library()
  → scan_library()
  → publish
  → 重算 missing
  → 记录 last_missing / last_rebuild / last_recovered
```

```text
同一缺失集合不重复重试，避免每次启动都全量扫。
```

## 8. 歌单

```text
data/curated/playlists.json
```

```text
开发时 data = 项目/data；
打包后 data = ~/Library/Application Support/momo uta/data。
```

结构：

```json
{
  "lists": [{"id": "default", "name": "默认歌单"}],
  "members": {"default": ["uid1", "uid2"]},
  "list_order": ["user:..."],
  "open": ["default"]
}
```

```text
一个歌单就是一串 uid。
同一首歌可以出现在多个歌单。
默认歌单置顶、不可改名/删除。
```

```text
build(lib)
  → 把 uid 映射成当前 CACHE entry
  → 找不到的 uid 保留在文件里，只增加 missing 计数
```

```text
不清洗 members，避免临时缺文件导致歌单内容被误删。
```

## 9. 歌单操作

```text
list_create / list_rename / list_delete / list_clear
entry_remove / entries_remove
entry_move / entries_move
entry_reorder / list_reorder
ui_open
```

```text
所有写操作都走 fsio.locked + atomic_write。
默认歌单锁定规则在 service/core 检查。
```

### 9.1 右键移动

歌曲列表支持选中一首或多首后：

```text
右键 → 移动到歌单 ▸
```

行为：

```text
鼠标悬停 100ms 或点击展开二级菜单
Shift+F10 打开歌曲菜单
方向键 / Home / End 选择目标
Enter 移动，Esc 关闭
目标歌单排除源歌单
移动到目标末尾
```

完成移动或移除后：

```text
聚焦源歌单中选中项的下一条
没有下一条则聚焦前一条
源歌单为空则聚焦标题
```

接口仍是 `entries_move`，返回实际移动数量 `moved`。

## 10. imports

```text
data/curated/imports.json
```

```json
[{"audio": "/path/a.mp3", "title": "曲", "artist": "歌手"}]
```

```text
用于导入过、但不在 music_dirs 里的音频。
启动加载时作为缺失 uid 的补充路径。
```

```text
写入前加文件锁。
不是曲库身份来源。
```

## 11. 导入

两个入口，语义不同：

```text
导入音乐
  import_paths(paths, with_lrc=False)
  → 只收音频
  → 目录里的 .lrc / .nhlrc 不扫描
  → 显式选中的 .lrc / .nhlrc 被拒绝并提示
  → 不写 nhlrc
  → 歌词走待匹配

导入音乐+LRC
  import_paths(paths, with_lrc=True)
  → 收音频和显式/目录里的 .lrc / .nhlrc
  → 按 stem / 同目录唯一配对
  → nhlrc 优先
  → 校验 valid_import
  → LRC.import_text 写 nhlrc
  → 显式 V1 输入不再读取
```

```text
已有 data/lyrics 下的 nhlrc 仍然按 uid 优先；
导入音频不会动它。
```

```text
不是 .lrc 导入 LRC 编辑器那条路径。
```

```text
配对、校验失败：
  音频仍可加入曲库
  但歌词不写
```

## 12. offset

```text
data/curated/song_meta.json
{ "<uid>": {"offset": 0.4} }
```

```text
offset 是歌曲属性，不是文件名属性。
```

```text
song_payload 读取
ui_offset 写入
```

```text
offset 只影响歌词/波形显示对齐，
不改音频，不写 nhlrc。
```

## 13. 已知限制

```text
1. CACHE 是已加载子集，不是全库。
2. idx 会随加载/重建变化。
3. 歌单暂时找不到的 uid 会保留，并计入 missing。
4. 自动重建只由缺失触发。
5. 目录导入是同步的，大批量会让 UI 等待。
6. imports 是路径登记，不是身份。
```

## 14. 测试

```text
tests/test_library.py
tests/test_library_index.py
tests/test_library_selective.py
tests/test_library_identity.py
tests/test_playlists_api.py
tests/test_playlists_move.py
tests/test_importing.py
```

## 15. 相关

```text
fingerprint.md
cache.md
lyrics-matching.md
lrc-editor.md
http-api.md
```
