# 网易云 LRC 清理

> 只处理与已删除重复音频对应的 LRC，以及明确的孤立重复 LRC。

## 扫描

```text
LRC 文件：108
完全同内容组：3
  27 份 [00:00.00]暂无歌词
  14 份 [00:05.00]纯音乐，请欣赏
  2 份 Unleash the Magic
```

## 没有按内容全局去重

`暂无歌词`、`纯音乐，请欣赏` 是每首歌各自的占位文件：

```text
不同歌曲内容相同
但删到只剩一份会破坏其它歌曲的 LRC 配对
```

所以这两组没有跨歌曲删除。

## 实际处理

### 保留歌词并改名

这些 LRC 属于被删除的重复音频，但保留音频没有对应 LRC，
因此改名到保留音频：

```text
Aimer - 春はゆく (1).lrc
→ Aimer - 春はゆく.lrc

Lia - 鳥の詩 (1).lrc
→ Lia - 鳥の詩.lrc

sajou no hana - グレイ (1).lrc
→ sajou no hana - グレイ.lrc
```

### 移入回收站

```text
未知歌手 - I will save you without fail!.lrc
  对应音频已删除；内容为“暂无歌词”占位

未知歌手 - EX1.lrc
  对应音频已删除；内容为“暂无歌词”占位

Rebecca Shoichet,Iris Quinn - Unleash the Magic.lrc
  没有对应音频；另一份完整 LRC 仍保留
```

回收站：

```text
~/.Trash/momo_uta_lrc_duplicates_20261124-041756
```

## 结果

```text
LRC 108 → 105
移入回收站：3
改名保留：3
同名但内容不同/占位文件：未动
```
