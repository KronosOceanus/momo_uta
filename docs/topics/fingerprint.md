# 音频指纹

> 本文说明歌曲身份 `uid` 的算法、性质、缓存和已知边界。
> 分层与写入边界见 [架构文档](../architecture.md)，nhlrc 命名见 [nhlrc 文档](nhlrc.md)。

## 0. 一句话

```text
uid = 音频指纹
    = 与路径无关的歌曲身份
```

```text
移动/改名不变。
同一段音频的副本共享同一个 uid。
重新压制/剪辑变成另一个 uid。
```

它不是文件校验，也不是音乐识别。

## 1. 用途

`uid` 用于：

```text
nhlrc 文件名
library.BY_UID
歌单成员
歌词/翻译/offset 的关联键
前后端歌曲 API
```

```text
idx 只是曲库展示位置，不是身份。
key 是历史字段，不是身份。
```

## 2. 算法

```text
sha1(
  时长字符串 + "|" +
  文件大小 + "|" +
  三个采样点的字节
)[:12]
```

伪代码：

```python
raw = f"{duration_s}|{size}|".encode() + samples
uid = sha1(raw).hexdigest()[:12]
```

### 2.1 时长

```text
用 mutagen 读取音频时长
保留 1 位小数
读不到时使用 "na"
```

```text
wav 没有 INFO 块时，使用标准库 wave 兜底。
```

### 2.2 采样

```text
CHUNK = 32 KiB
POSITIONS = (0.25, 0.5, 0.75)
```

```text
文件 > 96 KiB：
  25% / 50% / 75% 各读 32 KiB
  偏移以文件大小计算

文件 <= 96 KiB：
  从开头连续读 96 KiB
```

```text
采样只读字节，不修改原文件。
```

### 2.3 输出

```text
12 位十六进制
48 bit
```

```text
不是密码学安全哈希。
只用于稳定身份。
```

## 3. 什么不变，什么会变

| 操作 | uid |
|---|---|
| 移动文件 | 不变 |
| 改名 | 不变 |
| 复制一份 | 相同 |
| 重新压制 | 改变 |
| 剪辑/拼接 | 改变 |
| 只改 ID3 标签/封面 | 可能改变 |
| 同内容换容器 | 改变 |
| 改文件名但字节不变 | 不变 |

```text
只改标签/封面可能改变文件大小或采样位置，
所以 uid 可能变。
这是已知限制，不是缓存 bug。
```

## 4. 与路径无关

```text
指纹输入不包含路径。
路径只作为缓存索引的 key。
```

```text
音频移动后：
  重新扫描会按内容算出同一个 uid
  旧 nhlrc 仍然对应同一首歌
```

## 5. 读失败回退

文件读不了时：

```text
uid = md5(path)[:12]
```

包括：

```text
文件不存在
权限不足
损坏到无法读取
测试占位文件
```

```text
这个回退只保证“有一个稳定 id”。
它不保证移动后不变。
```

```text
正常文件走内容指纹，不走路径回退。
```

## 6. 索引缓存

```text
data/cache/fingerprints.json
```

结构：

```json
{
  "_v": "源码 hash",
  "/path/to/a.mp3": {
    "size": 123456,
    "mtime": 1700000000.0,
    "fp": "abcdef123456"
  }
}
```

规则：

```text
key：文件路径
校验：size + mtime
命中：直接返回 fp
失效：重新读文件计算
版本：_v 是源码 hash，源码变化自动失效
```

```text
索引只缓存，不是权威。
删除索引只会导致重新计算。
```

## 7. 失效与重算

```text
size/mtime 变化
  → 缓存失效
  → 重新计算

force=True
  → 绕过缓存
  → 强制重算

library.refresh(uid)
  → 使用 force_fp
  → 用于文件内容变了、需要换 uid 的场合
```

```text
索引写入使用原子替换。
索引在进程内聚合，flush 时写盘。
```

## 8. 与 nhlrc 的关系

```text
nhlrc 文件名：
  <title> - <artist>.<uid>.nhlrc
```

```text
LRC.store_path 按 uid 后缀查找已有文件。
```

```text
同一段音频的多个副本
  → 共享同一个 uid
  → 共享同一份 nhlrc

重新压制
  → 新 uid
  → 新 nhlrc
```

## 9. 索引 API

```python
fingerprint(audio, force=False) -> uid
paths_for_uids(uids) -> {uid: [path, ...]}
prune(valid_paths)
flush()
```

```text
paths_for_uids 只检查文件是否存在；
真正加载时还会重新计算/验证 uid。
```

## 10. 已知限制

```text
1. 12 位 hex = 48 bit，理论上存在碰撞。
   当前没有碰撞处理；BY_UID 以后写入者为准。

2. 只改标签/封面可能改变文件大小和采样位置，
   导致 uid 变化。

3. 读失败回退到路径 md5；
   路径变了 id 就变。

4. fingerprints.json 没有跨进程文件锁。
   当前按单进程桌面应用设计。

5. paths_for_uids 不校验 size/mtime；
   它只负责快速找候选路径，最终以实际加载为准。
```

```text
这些是身份设计的边界，不是缓存 bug。
```

## 11. 测试

```text
同字节不同路径 → 同 uid
内容变化 → uid 变化
索引复用 → 不重复计算
读失败 → 路径回退
音频移动后 → nhlrc 仍能找到
```

测试文件：

```text
tests/test_fingerprint.py
```

## 12. 不做

```text
不做音频去重
不做音乐识别
不做安全校验
不做跨设备指纹同步
不做碰撞合并
```

## 13. 相关

```text
nhlrc 命名/身份 → nhlrc.md
缓存失效/删除 → cache.md
```
