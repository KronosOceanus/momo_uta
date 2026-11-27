# 歌单与 NHLRC 导入导出

> 状态：设计稿，未实现。
> 目标：把歌单作为稳定标准，支持歌单 + nhlrc 的 ZIP 导出/导入；音频缺失时不再让歌单条目消失。

## 1. 产品目标

```text
歌单是标准
歌词跟着歌单走
音频缺失也要显示
```

导出：

```text
全部歌单
全部相关 nhlrc
manifest
```

导入：

```text
支持 ZIP
支持音频 + LRC 的常规导入
支持只有歌单和歌词、暂时没有音频
```

不包含：

```text
音频文件
封面
缓存
人声分离结果
WebDAV
```

## 2. 核心原则

### 2.1 歌单成员不因音频缺失而消失

当前行为：

```text
playlists.json 仍保留 uid
→ 曲库找不到
→ PL.build 只返回可解析 items
→ 前端直接不显示
```

新行为：

```text
playlists.json 保留 uid
→ 曲库找不到
→ 返回 missing_items
→ 歌单界面灰显“缺失”
```

### 2.2 区分两种情况

```text
音频缺失
  = missing
  = 无歌词
  = 无法播放

音频存在 + 没有 nhlrc
  = 正常歌曲
  = 可播放
  = 显示“无词”
```

不能把两者混成同一种状态。

### 2.3 缺失歌曲不进入播放层

```text
missing_items 只用于歌单显示
不进入 NH.LIB
不进入播放
不进入上一句/下一句
不进入歌词编辑
```

## 3. 数据结构

### 3.1 playlists.json

保留现有字段：

```json
{
  "lists": [{"id": "default", "name": "默认歌单"}],
  "members": {"default": ["uid1", "uid2"]},
  "list_order": [],
  "open": ["default"]
}
```

新增可选字段：

```json
{
  "track_meta": {
    "uid1": {"title": "fairytale", "artist": "Kalafina"}
  }
}
```

用途：

```text
音频存在：正常曲库信息优先
音频缺失：用 track_meta 显示标题/歌手
ZIP 导入：保留 manifest 信息
```

兼容：

```text
没有 track_meta 的旧文件正常读取
旧缺失条目退回显示 uid
```

### 3.2 PL.build 返回结构

```json
{
  "id": "default",
  "name": "默认歌单",
  "items": [],
  "missing_items": [
    {
      "uid": "a8bfa...",
      "title": "fairytale",
      "artist": "Kalafina",
      "missing": true,
      "has_lyric": false,
      "playable": false
    }
  ],
  "missing": 1
}
```

约束：

```text
items 只包含可播放歌曲
missing_items 只包含不可解析成员
NH.LIB 仍然只从 items 构建
```

## 4. 歌单界面

### 4.1 显示

缺失项保留在歌单原位置，灰显：

```text
01 喜劇 · 星野源
02 缺失歌曲：fairytale · Kalafina
03 群青 · YOASOBI
```

没有 track_meta 时：

```text
缺失歌曲
uid: a8bfa...
```

### 4.2 交互

```text
点击：提示“歌曲文件缺失”
不可播放
不可编辑歌词
不可匹配歌词
可以移除
可以右键
```

不显示：

```text
无词
有人声
波形
播放按钮
```

### 4.3 计数

建议显示：

```text
5 / 6
```

表示：

```text
6 个歌单成员
5 个可用
```

或：

```text
6  其中 1 缺失
```

第一版建议使用：

```text
可用数 / 总数
```

## 5. ZIP 格式

### 5.1 文件名

```text
momo-uta-bundle-YYYYMMDD-HHMM.zip
```

### 5.2 目录

```text
momo-uta-bundle-20261127-1400.zip
├─ manifest.json
├─ playlists.json
└─ lyrics/
   ├─ 喜劇 - 星野源.a8bfa43e5293.nhlrc
   └─ ...
```

分层固定为：

```text
manifest.json
playlists.json
lyrics/
```

后续如需扩展，只增加新文件，不改变已有路径含义。

### 5.3 manifest.json

```json
{
  "format": "momo-uta-bundle",
  "format_version": 1,
  "created_at": "2026-11-27T14:00:00+08:00",
  "app_version": "1.2.5",
  "audio_included": false,
  "tracks": [
    {
      "uid": "a8bfa43e5293",
      "title": "喜劇",
      "artist": "星野源",
      "lyrics": "lyrics/喜劇 - 星野源.a8bfa43e5293.nhlrc",
      "has_lyrics": true,
      "playable": true
    }
  ],
  "missing_lyrics": []
}
```

约束：

```text
不写绝对路径
不写用户目录
不写音频路径
同一 uid 只出现一次
```

## 6. 导出范围

导出全部歌单：

```text
默认歌单
用户歌单
空歌单
缺失条目
```

同一首歌在多个歌单里只导出一次 nhlrc。

缺失歌曲：

```text
保留歌单成员
manifest 写 has_lyrics=false
不生成空 nhlrc
```

## 7. 导出流程

入口：

```text
歌单区域
→ 更多菜单
→ 导出歌单包
```

流程：

```text
读取 playlists.json
→ 收集所有 uid
→ 查 LIB.BY_UID
→ 查 nhlrc
→ 生成 manifest
→ 写 zip
→ 保存到用户选择位置
```

结果提示：

```text
歌单数
歌曲数
歌词数
缺失歌词数
```

导出不读取：

```text
音频
波形缓存
人声缓存
```

## 8. 导入流程

### 8.1 只有 ZIP

```text
选择 zip
→ 校验 manifest
→ 校验路径安全
→ 合并歌单
→ 按 uid 匹配本机歌曲
→ 匹配到：正常歌曲
→ 匹配不到：missing_items
→ nhlrc 暂存
```

如果 ZIP 不带音频：

```text
歌单能恢复
歌词能落库
缺失歌曲灰显
暂时不能播放
```

### 8.2 ZIP + 音频

用户另外选择音频时：

```text
音频走现有导入流程
→ 生成 uid
→ 用 uid 匹配 ZIP 里的歌单成员
→ 挂上 nhlrc
→ 缺失状态解除
```

### 8.3 现有音频 + LRC 导入

保留现有入口：

```text
音频 + LRC
→ 生成 uid
→ 写 nhlrc
→ 加入歌单
```

ZIP 只是另一种来源，不替代原有音频导入。

## 9. 匹配规则

优先级：

```text
1. uid 精确匹配
2. 标题 + 歌手匹配
3. 不匹配 → missing
```

第一版以 uid 为主。

标题/歌手匹配只作为提示，  
不自动把歌词挂到不确定的歌曲上。

## 10. 歌词暂存

ZIP 只有歌词、没有音频时，不能依赖音频指纹路径。

建议：

```text
data/lyrics/pending/<uid>.nhlrc
```

manifest 保留：

```text
uid
title
artist
```

找到音频后：

```text
生成正式 store_path
移动/复制 pending 文件
删除 pending
```

第一版如果只做“有音频 + ZIP 歌词”，  
可以暂不启用 pending；  
但格式必须预留。

## 11. 冲突处理

导入时如果本机已有同一歌曲：

```text
版本相同：跳过
本机更新：不覆盖
ZIP 更新：提示后覆盖
```

默认策略：

```text
不静默覆盖本机歌词
```

歌单合并：

```text
同名歌单：合并成员
不同名：新建
```

第一版可以先只支持：

```text
导入为新歌单
或覆盖当前歌单
```

需要在实现前定死。

## 12. 安全

必须防：

```text
zip slip
绝对路径
../ 路径
符号链接
超大解压
超多文件
非法 Unicode
```

限制：

```text
只解压 manifest.json
playlists.json
lyrics/*.nhlrc
```

忽略其他文件。

文件名清洗：

```text
/ \ : * ? " < > |
控制字符
超长名称
```

## 13. 需要修改的位置

```text
core/playlists.py
  track_meta
  build 返回 missing_items

service/playlist.py
  _lists 透传 missing_items

static/12-library.js
  渲染缺失项
  计数
  点击不可播放

service/export_bundle.py
  新增导出服务

service/import_bundle.py
  新增导入服务

http/routes.py
  /api/export/bundle
  /api/import/bundle

app/__main__.py
  二进制保存/选择 zip 的接口
```

## 14. 测试

### 歌单缺失

```text
members 有 uid
LIB 没有
→ items 为空
→ missing_items 有一条
→ NH.LIB 不包含它
```

### 导出

```text
全部歌单
重复 uid 只导一次
缺失歌词不生成空文件
manifest 路径相对
```

### 导入

```text
合法 zip
缺失音频
重复 uid
冲突版本
zip slip
空歌单
```

### UI

```text
缺失项灰显
点击提示
不可播放
计数显示
```

## 15. 第一版范围

建议第一版做：

```text
导出全部歌单
导出 nhlrc
导入 zip 恢复歌单和歌词
缺失歌曲灰显
```

暂不做：

```text
重新定位音频
标题/歌手自动匹配
云端同步
音频打包
```

## 16. 结论

```text
歌单是标准
缺失不再消失
ZIP 是歌单 + 歌词包
音频仍然单独导入
缺失项可显示、可移除
```

这样既支持备份/迁移，  
也不会破坏现有播放和 LRC 编辑链路。
