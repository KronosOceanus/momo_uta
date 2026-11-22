# LRC 编辑器

> 本文说明 LRC 编辑模式的数据模型、编辑操作、保存/导入/导出和翻译列。
> 文件格式见 [nhlrc](nhlrc.md)，状态组合见 [player-state](player-state.md)。

## 0. 一句话

```text
LRC 编辑器 = 一张可编辑的 ERROWS 表
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
  [{t, text, trans}, ...]

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
EROWS 保留文件顺序和未打点的草稿行。
播放视图只使用有时间戳的行。
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

### 原文

```text
输入 → 更新 r.text
Enter → 在光标处拆行
行首 Backspace/Delete → 合并到上一行
多行粘贴 → 插入多行
```

### 翻译

```text
输入 → 更新 r.trans
Enter → 失焦，不拆行
```

```text
翻译不进入正文，不改变 r.text。
```

### 加行 / 删行

```text
加行 → 在选中行后插入空行
删行 → 删除选中行或当前行
```

### ↤ 绑定时间

```text
先在波形上点一个位置
再点行内 ↤
  → r.t = NH.MARK
  → 光标移到下一行
```

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

```text
保存成功后更新 LRC_VERSION。
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
不清空 ERROWS[i].trans
不 markDirty
```

保存：

```text
lrcPayload()
  → 每行带 trans
  → 服务端写 nhlrc 尾部 trans
```

```text
关闭列后保存，trans 仍然保留。
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
4. 每次进入编辑器翻译列都重置为关。
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
```

## 17. 相关

```text
nhlrc 格式 → nhlrc.md
缓存/备份 → cache.md
播放器状态 → player-state.md
```
