# LRC 编辑器

> 本文说明 LRC 编辑模式的数据模型、编辑操作、保存/导入/导出和翻译列。
> 文件格式见 [nhlrc](nhlrc.md)，状态组合见 [player-state](player-state.md)。

## 0. 一句话

```text
LRC 编辑器 = 一张可编辑的 EROWS 表
            + 自动保存队列
            + 版本校验
            + 导入/导出/删除/恢复
```

它不是另一套歌词存储。最终仍然写 nhlrc。

## 1. 入口与退出

### 进入

```text
顶部“LRC 编辑模式：关”
  → openLrcEditor(true)
  → GET /api/lrc?action=load
  → VIEW_MODE = lrc
  → 建立 EROWS
```

进入时检查：

```text
当前有 S
不在 matching
load token 仍然有效
lrcOpen token 仍然有效
```

### 退出

```text
再点一次“LRC 编辑模式：开”
  → NH.load(uid, false, 'normal')
```

```text
切歌、双击歌曲、开始等路径也可能离开 LRC。
离开前会 flush 草稿。
```

## 2. 数据模型

```text
NH.EROWS
  [{t, text, trans, lid, tokens}, ...]

NH.ESEL
  当前行

NH.SEL
  多选行 Set

NH.UNDO / NH.REDO
  快照栈

NH.EDIRTY
  有未保存修改

NH.LRC_VERSION
  nhlrc 全文件版本

NH.LRC_METADATA
  [ar:] / [ti:] / [offset:] 等原始元数据
```

```text
EROWS 保留文件顺序、空行和未打点的草稿行。
播放视图只使用有时间戳且文本非空的行。
```

## 3. 表格布局

每行：

```text
[行号] [时间戳] [↤] [原文] [翻译?] [✕]
```

翻译列关闭时：

```text
[行号] [时间戳] [↤] [原文........................] [✕]
```

翻译列打开时：

```text
[行号] [时间戳] [↤] [原文..............] [翻译..............] [✕]
```

```text
翻译打开时，表格左边距从 30% 改为 10%。
```

## 4. 行操作

### 时间戳

```text
00:12.34
```

```text
输入合法 → 更新 r.t
输入非法 → 恢复旧值并提示
清空 → r.t = null
Enter → 失焦提交
```

写入前检查：

```text
prev.t <= t <= next.t
```

允许相同时间；倒序时：

```text
toast 提示
输入恢复旧值
不 snapshot
不 markDirty
```

绑定时同样检查。

### 原文

```text
输入 → 更新 r.text
Enter → 在光标处拆行
行首 Backspace/Delete → 合并到上一行
多行粘贴 → 插入多行
```

IME 组合中不更新 EROWS：

```text
compositionstart
  → 只做一次 snapshot

compositionend / blur
  → 一次性 retokenizeRow + markDirty
```

避免日语输入法中间态删除 token。

### 翻译

```text
输入 → 更新 r.trans
Enter → 失焦，不拆行
```

```text
翻译不进入正文，不改变 r.text。
```

翻译列默认开启：

```text
打开编辑器时 TRANS_EDIT = true
```

翻译修改也会进入撤销栈：

```text
第一次输入 → snapshot
连续输入 → 不重复 snapshot
失焦 → 重置编辑批次
```

### 加行 / 删行

```text
加行 → 在选中行后插入空行
删行 → 删除选中行或当前行
```

空行会：

```text
显示在 LRC 编辑器
保留在正文
是 rows 中的 kind=blank
不出现在播放行
不写入 lines / trans
```

```text
lyric → blank
  → lid/tokens/trans 清空

blank → lyric
  → 新 lid、新 token、空 trans
```

### 行 / token 身份

LRC 编辑器加载时同时拿到：

```text
lid
tokens: [{tid, start, end, base, ruby, level}]
```

文本编辑：

```text
未改动区间的 token
  → 保留 tid/ruby/level
  → start/end 随文本平移

改动区间的 token
  → 丢弃 tid
  → 后端重新注音
  → 分配新 tid
```

行操作：

```text
插入行 → 新 lid
删除行 → 删除该行身份
拆行   → 原内容所在侧保留 lid；空侧新 lid
合并行 → 非空侧保留 lid；左边为空时用右边内容的 lid
        右侧 token 平移
```

保存时 `lrcPayload()` 会带：

```text
id
kind
text
t
lid
trans
tokens: [{tid, start, end, base, ruby, level}]
```

服务端按 `lid + tid + span/base` 保留读音，不按 base 猜测。
正文改了但 token 只覆盖一部分时，服务端先补齐分段，再恢复未改 token。

完整格式见 [nhlrc-token-ids](nhlrc-token-ids.md)。

### ↤ 绑定时间

```text
先在波形上点一个位置
再点行内 ↤
  → 检查时间顺序
  → r.t = NH.MARK
  → 光标移到下一行
```

时间不合法则拒绝绑定并提示。

## 5. 选择

```text
单击 → 当前行
Cmd/Ctrl+点击 → 多选
Shift+点击 → 范围选择
Shift+拖动 → 框选
Cmd+A → 全选
Delete/Backspace → 删除选中行
```

```text
点击输入框不会抢行选择。
```

## 6. 撤销 / 重做

```text
Cmd+Z
Shift+Cmd+Z
```

```text
snapshot() 保存整个 EROWS 的 JSON。
UNDO 上限由 UI.undo_steps 控制。
```

文本输入按“编辑批次”压栈：

```text
beginTextEdit(i)
  → 同一行第一次输入时 snapshot()
  → 连续输入不重复压栈
  → blur / Enter / 撤销 / 重做后重新开始
```

```text
翻译和原文一起进入快照。
```

## 7. 自动保存

```text
输入 → markDirty()
  → EDIRTY = true
  → EDIT_REVISION++
  → 清除旧 SAVE_T
  → autosave_ms 后 saveLrc(true)
```

### 保存队列

```text
SAVE_PENDING
```

```text
同一会话的保存串行。
保存开始后，编辑继续产生的 revision 不会被这次响应清掉。
```

### 版本

```text
saveLrc 发送 NH.LRC_VERSION
服务端版本不匹配 → conflict
冲突 → 保留草稿，不覆盖
```

冲突选择：

```text
重新加载服务端（放弃本地草稿）
用本地覆盖（先取最新版本）
取消
```

```text
保存成功后更新 LRC_VERSION。
普通页改读音响应同时更新 NH.S.version。
```

### 保存响应

```text
save_rows → ok + version + refresh 状态
```

```text
nhlrc 编辑器不再依赖响应 ids 合并；
lid/tid 已在 rows 中。
```

### 保存提示

```text
未保存…
已保存 12:34:56
已保存，但曲库刷新失败...
保存失败
```

```text
曲库刷新失败不等于歌词没保存。
```

## 8. 离开编辑器

```text
LRC → 普通
LRC → 另一首歌
```

```text
EDIRTY 或 SAVE_PENDING
  → flushLrc()
  → 保存失败 → 不离开
  → 保存成功 → 继续
```

```text
load 期间 setLrcLocked(true)
finally setLrcLocked(false)
```

## 9. 翻译列

按钮：

```text
翻译：关 / 翻译：开
```

```text
默认关。
每次重新进入编辑器都会恢复为关。
```

打开：

```text
每行显示第二输入框
EROWS[i].trans 可编辑
```

关闭：

```text
只隐藏输入框
不清空 EROWS[i].trans
不 markDirty
```

保存：

```text
lrcPayload()
  → rows
  → 每行带 kind/t/text/trans/lid/tokens
  → 服务端写 v2 尾部
```

```text
关闭列后保存，trans 仍然保留。
```

保存契约：

```text
metadata 原样透传
  → [ar:] / [ti:] / [offset:] 不因首次保存或改读音丢失
  → 保存时从当前文档带入

trans_lang 原样透传
  → 改读音、改翻译、普通保存都不改写语言标签
  → 只有显式改语言时才变

translations 是 body-keyed 快照
  key = 编辑器 body 行号

{}            → 清空全部翻译
"行": ""      → 清空该行翻译
缺省          → 先看 lines[].trans，再沿用旧文档
```

```text
只有 kind=lyric 的行会写入 trans。
blank / metadata 留在正文，但不写 lines/trans。
```

## 10. 导入

```text
LRC 工具栏“导入”
  → pick_lrc_text
  → 用户确认覆盖
  → replaceLrc({action:'import_lrc'})
```

```text
导入前等待 SAVE_PENDING。
导入期间 LRC_REPLACING + LRC_LOCKED。
导入成功 → 重新 openLrcEditor。
```

```text
导入不是合并，是整份替换。
旧读音和旧翻译不保留。
V1 输入不再支持；只接受 v2。
```

统一校验由 `lrc_files.valid_import` 执行，详见 [nhlrc](nhlrc.md) 的导入校验。

## 11. 导出

```text
LRC 工具栏“导出”
  → /api/lrc?action=export
  → 生成 nhlrc + 纯 lrc
  → 根据保存文件名选择内容
```

```text
.nhlrc：正文 + 读音 + 翻译
.lrc：只有正文，不混翻译
```

```text
导出使用当前编辑行，不要求先保存。
rows 模式下直接序列化 rows。
旧/缓存模式下先按正文还原 rows，再写 v2。
空行、metadata 位置、译文和身份原样带出。
trans_lang 原样带出。
```

## 12. 删除 / 恢复最初

### 删除

```text
删除这首歌的歌词文件
  → 写 disabled nhlrc
  → 保留备份
  → 退出 LRC
  → 回普通页
```

```text
删除失败时草稿仍算未保存。
```

### 恢复最初

```text
读取备份状态
  → 没有备份 → 提示
  → 用户确认
  → replaceLrc({action:'restore'})
```

```text
恢复会替换当前编辑内容。
```

## 13. 读音编辑

读音编辑不在 LRC 表格里做。

```text
退出 LRC → 普通歌词/振假名模式
  → 点读音候选
  → /api/line
  → applyEdit
```

```text
LRC 编辑器负责时间轴和文字；
读音 picker 负责逐词读音。
```

## 14. 关键边界

```text
LRC_LOCKED
  编辑/flush 锁；inert 表格和工具栏

LRC_REPLACING
  导入/恢复/删除期间禁止切歌

SAVE_PENDING
  保存队列，不是排他锁

LRC_VERSION
  全文件版本，不是 nhlrc 的 v 字段

TRANS_EDIT
  显示开关，不是数据删除
```

## 15. 已知限制

```text
1. 表格操作大量使用整表重绘。
2. 时间戳不支持编辑区间写法。
3. 元数据不能直接在表格里编辑。
4. 每次进入编辑器翻译列默认重置为开。
5. 导入是整份替换，不做逐行合并。
```

## 16. 测试

```text
tests/lrc_editor.test.cjs
```

覆盖：

```text
进入/退出
拆行/合并
撤销/重做
保存串行
版本冲突
删除/恢复
导入
翻译列
时间顺序校验
IME 组合
冲突选择
```

## 17. 相关

```text
nhlrc 格式 → nhlrc.md
缓存/备份 → cache.md
播放器状态 → player-state.md
```
