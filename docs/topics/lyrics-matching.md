# 歌词匹配

> 本文只讲“怎么找到歌词、怎么选”，不展开 nhlrc 格式和翻译对齐。
> 格式见 [nhlrc](nhlrc.md)，缓存见 [cache](cache.md)。

## 0. 一句话

```text
输入：音频文件名里的 artist - title
来源：网易云搜索 + 歌词接口
输出：自动选一条 / 手动选一条
```

```text
本地 .lrc 导入不经过匹配。
路径配对是 importing.py 的职责。
```

## 1. 输入

从音频文件名取：

```text
artist - title
```

```python
split_name(stem)
  → artist, title
```

规则：

```text
只按第一个 " - " 拆
artist 会 clean_artist
title 不重命名
```

`clean_artist`：

```text
"甲,乙,甲乙" → "甲,乙"
```

```text
匹配只使用 artist / title / duration。
不读 nhlrc，不读歌单名。
```

## 2. 候选搜索

```python
search_candidates(title, artist)
```

查询：

```text
title artist
title
artist title
```

```text
合并去重
limit = search_limit
按 max_ids 截断
song/detail 补时长
```

```text
当前唯一来源：网易云。
```

## 3. 打分

```text
总分 =
  标题权重 40 +
  歌手权重 20 +
  时长权重 40
```

标题/歌手使用 `_match`：

```text
NFKC
小写
去标点/空格
完全相等，或较长一方包含较短一方
短标题不匹配子串（name_min_len）
```

时长：

```text
≤3s   1.0
≤10s  0.7
≤30s  0.3
>30s  0
```

```text
按总分降序。
```

## 4. 硬过滤

`accept_candidate` 实际检查：

```text
有 id
标题匹配
不是伴奏/卡拉OK/纯音乐
时长差 ≤ fallback_max_delta（默认 30s）
```

**当前没有歌手硬过滤。**

```text
artist 只参与打分，不参与 accept_candidate。
```

```text
同名不同歌手、标题和时长又接近时，
仍可能进入候选列表。
```

## 5. 排除规则

```text
data/curated/lyrics_exclude.json
```

匹配前对歌名做 `_norm`：

```text
NFKC
小写
去标点/空格
```

排除词包含：

```text
instrumental / inst. / karaoke
カラオケ / インスト / オフボーカル
伴奏 / 消音 / 纯音乐 / 无人声
piano ver / piano version
...
```

## 6. 抓正文

```python
fetch_candidate(candidate)
```

```text
网易云 lyric 接口
  → lrc
  → tlyric
  → valid_lrc
```

`valid_lrc`：

```text
至少一个时间戳
至少 min_content_lines 行有效内容
```

```text
不通过 → 候选作废，继续下一个。
```

### 6.1 tlyric 与翻译

```text
tlyric 是另一个 LRC 字段
不是 lrc 正文的一部分
```

```text
fetch_candidate / fetch_lyrics_by_id 同时返回 lrc + tlyric
```

```text
translations_from_lrc
  → 先 ±0.05s
  → 再 ±0.2s
  → 两边行数一致才按行序补齐
  → 仍配不上就丢弃
```

```text
trans 是稀疏行属性，不存时间戳。
```

```text
自动/懒匹配只把 tlyric 放进歌词缓存；
用户 pick 或保存 LRC 时才写进 nhlrc trans。
```

```text
普通页在原文下显示译文；LRC 编辑器的翻译列见 lrc-editor.md。
```

## 7. 自动匹配

```python
auto_match(title, artist, duration)
```

```text
搜索
  → 打分
  → 排序
  → 只试前 auto_try 个
  → 第一个通过 accept + valid 的返回
```

```text
不是“选最高分”，
是“按分数顺序找到第一个可用”。
```

## 8. 重新匹配

```python
rematch(uid)
```

```text
只搜索网络候选
不掺本地当前歌词
不读写歌词缓存
不写 nhlrc
```

```text
候选列表不标“当前正在用的是哪条”。
```

候选行只含：

```text
id / name / artist / duration / delta / source / score
```

```text
按分数降序。
```

## 9. 手动 pick

```python
pick(uid, candidate_id)
```

```text
fetch_lyrics_by_id
  → lrc + tlyric 一次显式返回
  → valid_lrc
  → translations_from_lrc
  → save_lyrics(mode="replace")
  → 重写 nhlrc
```

```text
旧读音不保留
旧翻译不保留
新正文 + 新翻译一起写
```

## 10. 懒匹配

```python
lazy_match(item)
```

```text
disabled 直接跳过
  → get_lrc(force=True)
  → LIB.refresh(uid)
```

```text
用于打开时没有歌词、后台匹配的阶段。
```

## 11. 缓存

```text
data/cache/lyrics/<md5(title|artist)>.json
```

键：

```text
NFKC(title)|NFKC(artist) → md5 16 位
```

正缓存：

```text
lrc / tlyric / lang / kana_ratio / source
```

负缓存：

```text
{miss:true, reason, checked_at}
```

```text
负缓存默认 7 天过期。
正缓存没有 TTL。
force / 删除缓存可立即重试；rematch 本身不读写歌词缓存。
```

```text
有 nhlrc 时，歌词缓存不参与歌词读取。
```

## 12. 扫描 CLI

```bash
python -m nihonco_player.core.lyrics_fetch --scan <folder>
```

```text
只扫描日文名文件
is_likely_song 排除 BGM/伴奏
逐首 get_lrc
写覆盖报告
```

```text
开发/评测工具，不是播放器主路径。
```

## 13. 已知限制

```text
1. 歌手不是硬过滤，只参与打分。
2. 同名不同版本可能选错。
3. 标题匹配是相等/包含，不是编辑距离。
4. 短标题不做子串匹配。
5. 正缓存没有 TTL。
6. 负缓存有 TTL，但失败原因不区分网络/无结果。
7. 只使用网易云一个来源。
8. 没有多候选并发抓取。
9. 没有用户可调的匹配阈值 UI。
10. 手动候选不显示“当前使用中”。
```

## 14. 测试

```text
tests/test_lyrics.py
tests/test_rematch.py
tests/test_negative_cache.py
tests/test_lrc_authority.py
```

覆盖：

```text
标题/歌手规范化
排除词
候选评分
自动匹配顺序
rematch 不读写歌词缓存
pick 重写歌词
disabled 跳过懒匹配
负缓存 TTL
```

## 15. 不做

```text
不做音乐识别
不做多源合并
不做自动修正歌名
不做缓存迁移
不在匹配阶段改写 nhlrc（pick 除外）
```

## 16. 相关

```text
nhlrc 格式 → nhlrc.md
缓存 TTL/失效 → cache.md
```
