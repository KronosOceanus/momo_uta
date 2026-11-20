# 歌词来源匹配

> 读者：要改"去哪找歌词、怎么挑版本、什么时候重新找"的人。
> 定位：讲清三个入口——自动匹配、懒匹配、重新匹配——各自查什么、怎么选。
> 自成一体：不依赖其它文档；只引函数名，不写行号。

## 0. 三十秒版本

```text
自动匹配（第一次找歌词）
  有本地缓存 → 直接用
  没有 → 网易云 search_candidates → 同一套过滤和打分 → 第一个有效候选
  → 写歌词缓存

懒匹配（打开时发现没歌词）
  先确认不是纯音乐 → POST /api/pl {action:"match"}
  → get_lrc(force=True) 强制联网 → 写缓存
  → match 返回后前端再拉一次 /api/song
  → 还有歌词就重载，没有就显示没匹配到

重新匹配（用户主动换版本）
  → 同一批网易云候选、同一套过滤
  → 选中后重写 data/lyrics 的 nhlrc 正文，读音重来
```

```text
三件事不要混：
  · 歌词从哪来（来源匹配）——本文
  · 歌词怎么存（nhlrc 格式/落盘）——另一层
  · 音频怎么认（指纹）——另一层
```

## 1. 匹配的三层

```text
① 名称层：歌名、歌手能不能对上
     NFKC 归一、去标点、忽略大小写
     歌名要求"相等，或长名包含短名（短名至少 4 字）"

② 版本层：同名不同版本（TV size / full / live / remix）
     主要靠时长差；差得越少分越高

③ 内容层：歌词本身是不是可用
     网络歌词必须带时间戳（无时间轴直接拒绝）
     有效歌词行 ≥ 3（排除"作词/作曲"这类）
     自动匹配与手动 pick 共用这一个判断
     例外：本地 nhlrc 草稿允许尚未打点
     假名占比用于标记语言（不直接淘汰，除了纯音乐判定）
```

## 2. 名字与歌手

### 2.1 从文件名切

```text
split_name(stem)
  "歌手 - 歌名"   → (歌手, 歌名)
  "歌名"          → ("", 歌名)

clean_artist
  "甲,乙,甲乙"   → "甲,乙"（去掉重复拼接）
```

```text
文件名是唯一输入：
  不读 ID3 标签，也不读 nhlrc 里的 [ar:]/[ti:]。
  所以文件名不规范时，匹配会跟着不准。
```

### 2.2 歌名匹配

```text
_match(want, got)
  a = NFKC(want).lower()，去掉标点
  b = NFKC(got).lower()，去掉标点
  a == b → 命中
  否则：短的一方长度 ≥ name_min_len（默认 4）且是长的一方的子串 → 命中
```

```text
为什么不给短标题做子串：
  "レイン" 会命中 "Dot Brain" 里的部分假名，造成错配。
所以短名只认完全相等。
```

### 2.3 排除

```text
is_excluded(name)
  读 data/curated/lyrics_exclude.json 的 patterns
  归一化后包含任一 pattern → 排除
  常见：伴奏、卡拉OK、off vocal、instrumental 等

is_likely_song(stem)
  扫库时排除明显不是歌的文件（BGM 作者、Theme/Piano/Remix 标题等）
  只影响"曲库里收不收"，不影响单次匹配
```

## 3. 时长与打分

### 3.1 时长来源

```text
本地时长：LY.audio_duration(file)
  用解码器读；读不到返回 0（0 表示"没有时长信息"）

候选时长：网易云详情接口返回的 duration
  毫秒 → 秒，保留 1 位小数
```

### 3.2 允许的时长差

```text
候选：fallback_max_delta 默认 30.0 秒
```

```text
30 秒用于网易云：要容纳 TV size / 剪辑版 / 前后奏差异。
```

### 3.3 分数

```text
score = 40 × 歌名是否匹配
      + 20 × 歌手是否匹配
      + 40 × 时长档位

时长档位（delta_tiers 默认 [3, 10, 30]）：
  ≤ 3s   → 1.0
  ≤ 10s  → 0.7
  ≤ 30s  → 0.3
  > 30s  → 0

最高 100 分；用于排序，不用于硬性淘汰（淘汰看 §3.2 的阈值）。
```

## 4. 来源与角色

### 4.1 网易云：唯一候选来源

```text
搜索：music.163.com/api/search/get
详情：music.163.com/api/song/detail（补时长/歌手）
歌词：music.163.com/api/song/lyric（lrc + tlyric）
```

```text
它负责：
  · 自动匹配的候选
  · 重新匹配的候选
  · 实际歌词文本
```

```text
自动与手动必须用同一批候选、同一套过滤；
否则会出现"自动找不到、手动能找到"。
```

### 4.2 不再参与主流程的来源

```text
MusicBrainz：只保留 mb_canonical 工具，当前匹配流程不再调用。
lrclib：只保留函数，当前匹配流程不再作为兜底。

原因：
  多一个来源就多一套候选/过滤/校验，
  很容易再次出现自动与手动结果不一致。
  如果以后要恢复，必须同时进入自动和手动候选，
  而不是只给自动加后门。
```

## 5. 自动匹配：`get_lrc`

```text
get_lrc(title, artist, duration=0, force=False)
```

### 5.1 缓存优先

```text
缓存文件：data/cache/lyrics/<md5(NFKC(title)|NFKC(artist))[:16]>.json

命中条件（未 force）：
  · 请求没带 duration → 直接返回缓存
  · 缓存里有 duration → 直接返回
  · 缓存是负缓存（miss）→ 直接返回 miss
  其它情况（请求带 duration，但缓存没按时长匹配过）→ 重新联网
```

```text
force=True：完全跳过缓存，重新联网（懒匹配用）。
```

### 5.2 匹配流程

```text
① search_candidates(title, artist)
     网易云三种查询拼法，最多 20 个 id，补详情
② accept_candidate(c, title, artist, duration)
     歌名 match、排除词、|时长差| ≤ fallback_max_delta
③ score_candidate 打分，按分数降序
④ 从上往下取前 10 个：
      fetch_candidate(c)
        → 取 lrc
        → valid_lrc：必须带时间轴、有效行 ≥ 3
     第一个通过的就是结果
⑤ 无论成败都写缓存（失败写负缓存）
```

```text
没有 duration 时同样走这条流程，只是不做时长过滤。
```

```text
自动和手动共用：
  search_candidates / accept_candidate / fetch_candidate / valid_lrc
```

### 5.4 缓存内容

```text
成功：
  {source, id, name, artist, duration?, lrc, lang, kana_ratio?, tlyric?,
   title, artist_q}

失败：
  {miss: true, reason}
  reason 可能是 no_candidate / mb_no_candidate / netease_no_match
```

```text
负缓存的目的：避免每次启动都为同一首没结果的歌联网。
代价：之后网上补了歌词，也不会自动发现；需要重新匹配或懒匹配（force）。
```

## 6. 懒匹配（打开时没歌词）

### 6.1 触发

```text
GET /api/song/<idx> 返回 pending=true（data/lyrics 没有、缓存也没有）
  → 前端先 commitAudio（能播），autoplay 则播
  → 等人声分离结果（§7）
     判定纯音乐 → 跳过匹配，提示"纯音乐（无人声）"
  → POST /api/pl {action:"match", idx}
```

### 6.2 后端

```text
service.playlist 收到 action=match
  → SONGS.lazy_match(item)
  → split_name(stem)
  → get_lrc(title, artist, duration=audio_duration(file), force=True)
  → 写歌词缓存
  → LIB.refresh(uid)
```

```text
注意：懒匹配不写 data/lyrics。
它只把歌词放进缓存；下一次 GET /api/song 时载荷读到缓存，
再按"有歌词"的流程自动落盘成 nhlrc。
```

### 6.3 前端等待

```text
POST match 是同步的：后端跑完 lazy_match 才返回。
  返回后前端 GET /api/song/<idx> 一次：
    不再 pending → 重新 load，正常显示
    仍然 pending → "没匹配到歌词（仍可播放）"
  不再空轮询 60 秒
```

```text
LOAD_REQUEST 每次自增；切歌后旧的匹配结果不会覆盖新页面。
```

## 7. 重新匹配（用户主动换版本）

### 7.1 候选：只来自网络

```text
POST /api/rematch {idx, duration}
  duration = 当前音频时长（前端传，0 则后端用 audio_duration）

流程：
  ① split_name
  ② 网易云搜索（"歌名 歌手" / "歌名" / "歌手 歌名"，最多 20 个 id）
  ③ 补详情（歌名/歌手/时长）
  ④ 过滤：歌名 match、排除词、|时长差| ≤ 30s
  ⑤ 打分：40 标题 + 20 歌手 + 40 时长档位
  ⑥ 当前正在用的 id 只在网络结果里出现时标 ●
  ⑦ 按"当前优先、分数降序"排序，取前 10
```

```text
不查缓存、不插本地候选。
自动匹配用的是同一批候选、同一套 accept_candidate。
```

### 7.2 选中：替换正文

```text
POST /api/pick {idx, id}
  ① fetch_lrc_by_id(id)（网易云）
  ② valid_lrc 不通过 → 拒绝
     必须带时间轴、有效歌词行 ≥ 3
     与自动匹配的内容校验完全一致
  ③ 把网络正文写进 data/lyrics/<歌名> - <歌手>.<指纹>.nhlrc
      · 旧文件先备份成 .bak
      · 旧读音全部丢弃
  ④ LIB.refresh → 重新生成 payload
```

```text
之后下一次 GET /api/song：
  读到新正文、没有尾部 → 自动按引擎重新注音 → 写回 nhlrc。

即使选中的正文和当前完全一样，也会照常重写一次（可用来"重置读音"）。
```

### 7.3 界面

```text
菜单标题：选一个（分数越高越可能是同一版）· 候选来自网络，不读本地缓存
每项：● 歌名 · 歌手 · mm:ss · 时长差 · 分数
点选后：换歌流程 → NH.load → 重新拉歌词 → 提示"已换成 …（N 行歌词）"
```

## 8. 导入时的匹配

### 8.1 导入音频 + 同目录歌词

```text
import_paths(paths, pool)
  · 按文件名配对：去掉编号/后缀后比较
  · 同名词曲文件 .nhlrc 优先于 .lrc
  · 配不上 → 进"待匹配"
  · .nhlrc 的读音先放进歌词缓存（nhlrc_annotations）
  · 不读源目录之外的歌词，也不改源文件
```

```text
首次打开这首歌时，缓存里的歌词/读音会落成 data/lyrics 的 nhlrc。
```

### 8.2 导入单个歌词

```text
POST /api/lrc {action:"import_lrc", idx, text}
  · 正文写进当前音频的 nhlrc
  · .nhlrc 的读音按文本对齐保留
  · 不沿用来源身份（来源不参与查找）
```

## 9. 失败、负缓存与重试

```text
网络失败：
  _get 超时 10 秒，异常吞掉返回 ""；该来源视为无结果

没结果：
  get_lrc 返回 None，写负缓存 {miss:true, reason}
  payload 继续 pending；前端拿到 match 返回后再查一次就放弃

想强制重试：
  · 重新匹配（重新搜网易云）
  · 懒匹配（force=True，会绕过负缓存）
```

```text
自动匹配没有候选/候选全部无时间轴 → 返回 None 并写负缓存。
```

## 10. 配置

```text
config/defaults.json → lyrics 组：
  fallback_max_delta    30.0   普通候选允许的时长差
  min_content_lines     3      有效歌词行下限
  name_min_len          4      短名子串匹配的最小长度
  kana_ratio_min        0.1    判日语的假名占比
  lang_min_chars        20     语言判定所需最少字数
  weights.title/artist/duration  40/20/40
  delta_tiers           [3,10,30] 时长档位
```

```text
data/config.json 可覆盖；改完重启生效。
排除词表：data/curated/lyrics_exclude.json（patterns 数组）。
```

## 11. 已知限制

```text
① 只从文件名取歌名/歌手
   ID3 标签、nhlrc 元数据都不参与；文件名不规范就会匹配错

② 只依赖网易云
   接口不可用/地区限制时没有自动兜底；需要手动重新匹配

③ 无时间轴歌词一律拒绝
   自动匹配、重新匹配 pick 使用同一判断

④ 同名版本靠时长
   TV size / full / live 时长接近时可能挑错；需要手动重新匹配

⑤ 负缓存会"记住失败"
   网上后来补了歌词也不会自动发现；要手动重新匹配/懒匹配

⑥ 重新匹配和自动匹配同源
   都只搜网易云，候选与过滤完全一致

⑦ 重新匹配会丢旧读音
   选中新歌词 = 正文替换 + 读音重来；旧读音只留在 .bak 里
```

## 12. 代码地图与测试

| 职责 | 位置 |
|---|---|
| 名称/语言/排除/打分 | `core/lyrics_text.py` |
| 来源查询（网易云，统一候选/过滤/校验） | `core/lyrics_fetch.py` |
| 缓存读写/本地 lrc | `core/lyrics_cache.py` |
| 自动/懒匹配、重新匹配 | `service/song.py` |
| 导入与配对 | `core/importing.py`、`service/playlist.py` |
| 路由 | `http/routes.py` |

```text
测试：
  tests/test_rematch.py     候选只来自网络、当前标记、选中替换
  tests/test_importing.py   文件配对、nhlrc 读音保留
  tests/test_playlists_api.py  懒匹配 action 接到 lazy_match
  tests/test_player_http.py 载荷/接口层
```
