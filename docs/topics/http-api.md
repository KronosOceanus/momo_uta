# 本机 HTTP API

> 本机桌面应用使用，不对外暴露、不做鉴权。
> 总线和分层见 [architecture](../architecture.md)。

## 0. 基本约定

```text
服务绑定 127.0.0.1 的随机端口
桌面壳启动服务
前端通过相对路径 /api/* 调用
```

```text
JSON 请求：Content-Type: application/json
JSON 响应：除特别说明外，统一带 ok
```

```text
ok:true   成功
ok:false  业务失败
409       版本冲突
400       参数/JSON 错误
500       未捕获异常
404       找不到资源
```

```text
HTTP 层由 http/routes.py 分发；
业务在 service/；
不直接暴露 core 文件。
```

## 1. GET

| 路径 | 说明 |
|---|---|
| `/` | 播放器 HTML，注入 `__CFG` 和 `data-theme` |
| `/static/*` | 静态 CSS/JS |
| `/api/pl` | 歌单列表 + 展开状态 |
| `/api/library` | 当前已加载 CACHE 快照 |
| `/api/song/<uid>` | 单曲 payload |
| `/audio/<uid>` | 音频流，支持 Range |
| `/api/wave/<uid>?src=mix|vocals` | 波形峰值 |
| `/api/jobs/active` | 活动人声任务 |
| `/api/jobs/<id>` | 单个 job |

### 1.1 `/api/pl`

```json
{
  "ok": true,
  "lists": [{"id": "default", "name": "默认歌单", "items": []}],
  "open": ["default"]
}
```

### 1.2 `/api/library`

返回当前已加载曲库的行数组：

```json
[
  {"idx": "0", "uid": "abcdef123456", "title": "曲", "orig": "曲",
   "artist": "歌手", "key": "legacykey", "group": "导入"}
]
```

注意：

```text
这是数组，不是 {ok:true, rows:...}。
/api/library 只代表 CACHE，不是 music_dirs 全量。
```

### 1.3 `/api/song/<uid>`

```text
有歌词：
  {uid, idx, key, title, artist, lines, trans, version, ...}

pending：
  {..., pending:true, lines:[]}

disabled：
  {..., disabled:true, lines:[]}
```

```text
只接受 uid，不接受 idx。
找不到 uid → 404 JSON。
```

### 1.4 `/audio/<uid>`

```text
非 JSON
Content-Type: 音频类型
Accept-Ranges: bytes
```

```text
404:
  no such song
  file missing
```

```text
前端 abort 时服务端捕获 BrokenPipe/Reset，
不写错误日志。
```

### 1.5 `/api/wave/<uid>`

```text
?src=mix      默认，原曲
?src=vocals   人声轨存在时用人声
```

```text
返回 {duration, step, audio_size, audio_mtime, peaks, source}
```

```text
没有 uid → 404 JSON
```

## 2. POST

### 2.1 `/api/pl`

必填：

```text
action
```

动作：

```text
list_create / list_rename / list_delete / list_clear
entry_remove / entries_remove
entry_move / entries_move
entry_reorder / list_reorder
ui_open / ui_offset / edit_clear / match
import / library_rebuild
```

```text
大多数返回 {ok, lists, missing_count, auto_rebuild}
```

### 2.2 `/api/line`

必填：

```text
uid / line / start / reading
```

```text
改一处读音
立即写 nhlrc
返回 line / ruby / rm / ky / rmH / kyH / version
```

### 2.3 `/api/rematch`

必填：

```text
uid
```

可选：

```text
duration
```

```text
只搜索网络候选
返回 {stem, candidates}
不读写歌词缓存、不写 nhlrc
```

### 2.4 `/api/pick`

必填：

```text
uid / id
```

```text
抓选定候选的 lrc + tlyric
按行对齐翻译
重写 nhlrc（旧读音、旧翻译不保留）
```

```text
失败 → 400 {ok:false,error}
```

### 2.5 `/api/import/one`

必填：

```text
paths
```

```text
音频 + 同名 .lrc/.nhlrc 的目录导入
import 可带 with_lrc；缺省只收音频，显式歌词会被拒绝并返回 rejected_lrc
返回 import_paths 结果 + lists
```

### 2.6 `/api/lrc`

必填：

```text
uid
```

动作：

```text
load / save / export / backup / restore
delete / import_lrc / load_rows / save_rows / edit_reading / playback
```

```text
save 带 version；冲突 → 409 {ok:false, conflict:true}
```

```text
load:
  v2 文档返回 model:2 + rows
  v1/旧文档返回 lines
  lines 是编辑器行，保留空行
  body_rows 同 lines
  每行可带 lid/tokens
  token 含 tid/start/end/base/ruby/level
  annotation i 仍按非空歌词行编号

save:
  lines 可包含空行
  服务端先映射 body_rows → 非空歌词行
  lid/tokens 随行提交
  translations 是 body-keyed 快照；{} 表示清空全部
  trans_lang 缺省时沿用旧文档
  响应可带 ids（回传新生成的 lid/token spans）
```

```text
load_rows / save_rows 是 v2 单一行文档入口
edit_reading 使用 lid + tid + version，不使用 line/start
playback 返回 v2 playable lines + body_index
export 返回 nhlrc + 纯 lrc
导出时空行保留，annotation 按非空行编号
metadata 的 before 映射到 body 行
trans_lang 原样带出
```

### 2.7 `/api/jobs`

```json
{"kind": "vocals|match|rebuild", "uid": "..."}
```

```text
vocals / match 需要可用 uid
rebuild 不需要
未知 kind → 400
```

```text
返回 job 对象：id / kind / state / stage
```

### 2.8 job 取消

```text
POST /api/jobs/<id>/cancel
POST /api/jobs/cancel_all
```

```text
cancel_all 只接受 {"kind":"vocals"}
```

### 2.9 `/api/theme`

必填：

```text
theme = dark | light
```

```text
写 data/config.json 的 player.ui.theme
更新当前进程 PUI
```

### 2.10 `/api/log`

```text
前端未捕获错误上报
60 秒最多 30 条
超过返回 {ok:false, skipped:true}
```

## 3. 错误形态

```text
400 缺少参数
400 请求不是合法 JSON
404 资源不存在
409 LRC 版本冲突
500 内部错误（写 app.log traceback）
```

```text
业务规则失败通常是 200 + {ok:false,error}
例外：
  /api/pick 失败 → 400
  LRC 冲突 → 409
```

```text
前端 api() 对 409 {ok:false, conflict:true} 当业务结果返回；
其他非 2xx 抛错。
```

## 4. 必填字段

```text
/api/pl          action
/api/line        uid, line, start, reading
/api/rematch     uid
/api/pick        uid, id
/api/import/one  paths
/api/lrc         uid
/api/theme       theme
```

```text
缺失 → 400，不进入 service。
```

## 5. 已知边界

```text
1. 不做认证，只绑定本机。
2. /api/library 返回数组，没有 ok 包裹。
3. /api/wave 失败时仍可能带 ok:false + error。
4. job 表在进程内存，重启丢失。
5. 没有 API 版本号。
6. 没有请求大小限制配置。
```

## 6. 相关

```text
architecture.md
lrc-editor.md
lyrics-matching.md
vocals-jobs.md
```
