# LRC 打轴编辑器

> 读者：要改打轴表格、时间戳、选择、撤销、自动保存、模式切换的人。
> 定位：讲清"从进入编辑模式到安全落盘"这条链路。
> 自成一体：不依赖其它文档；只引函数名，不写行号。

## 0. 三十秒版本

```text
进入 LRC 编辑模式
  → 前端 GET /api/lrc?action=load，拿 rows（t + text）和 metadata
  → 表格里改时间 / 改文本 / 加行删行 / 粘贴 / 从波形绑时间
  → 每次改动 markDirty()：1.5 秒后自动保存
  → POST /api/lrc {action:"save", version, lines:[{t,text}]}
  → 后端按内容对齐旧读音，写 data/lyrics/<歌名> - <歌手>.<指纹>.nhlrc
  → 返回后清 dirty，savehint 显示"已保存 HH:MM:SS"
```

```text
编辑器只改"时间 + 文本"。
读音（seg）不在这里改；保存时后端把旧读音按文本对齐带过去，
新行/改了字的行重新注音。
```

## 1. 模型

### 1.1 前端数据

```text
EROWS        [{t, text}, ...]      表格里的行（t 可为 null）
LRC_METADATA [{before, text}, ...] 元数据标签，例如 [ar:]、[ti:]
ESEL         当前行（单选）
SEL          多选集合（行号）
MARK         波形上最近一次点击的时间（秒），用于"绑定时间"
EDIRTY       有未保存修改
UNDO/REDO    JSON 快照栈（默认最多 50）
UNDO_STEPS   ui.undo_steps
```

```text
t 的单位是秒，精度 0.01；null = 这一行还没打时间
text 是纯文本（不含时间戳，不含元数据）
元数据不参与排序/编辑，保存时按原位置插回
```

### 1.2 与普通视图的区别

```text
普通视图：LINES 只含有时间戳的行；读音、左右栏、候选都在这里
编辑视图：EROWS 保留文件顺序和"未打点的行"；不显示读音，不显示右栏
```

```text
两套数据不会同时活动：
  进入/退出编辑模式都会重新从后端取一份数据。
```

## 2. 打开、关闭与模式

### 2.1 进入

```text
点「LRC 编辑模式」
  → openLrcEditor(true)
  → GET /api/lrc {action:"load"}
  → VIEW_MODE = 'lrc'
  → 用返回的 lines 覆盖 EROWS；metadata 存 LRC_METADATA
  → 清空选择/撤销栈/脏标记
  → 渲染表格；初始化波形（窗口/跟随/峰值）
```

```text
请求竞争保护：
  LRC_OPEN_REQUEST 每次进入自增；
  LOAD_REQUEST 变了（切歌）或又点了一次进入 → 丢弃旧响应。
```

### 2.2 退出

```text
再点一次「LRC 编辑模式」
  → load(当前 uid, false, 'normal')
  → load() 发现正在编辑：setLrcLocked(true) → flushLrc() → 取新载荷
  → VIEW_MODE='normal'，回到普通视图
```

```text
退出前必须先保存：
  flushLrc() 失败 → 不退出，提示"歌词保存失败，当前编辑已保留"。
```

### 2.3 与"振假名编辑模式"的关系

```text
VIEW_MODE 三态互斥：normal / lrc / kana。
  在 'lrc' 里点「振假名编辑模式」→ 先 load(..., 'kana') 退出打轴
  在 'kana' 里点「LRC 编辑模式」→ 直接进入 'lrc'
  在 'lrc' 里点「LRC 编辑模式」→ 先 load(..., 'normal') 退出
```

### 2.4 界面状态

```text
body.lrcedit      打轴模式（显示时间列/工具条/波形）
body.fak          振假名编辑模式
#lyr.inert        锁定时整个表格不可交互
#lrcrow2.inert    锁定时第二行工具栏不可交互
```

## 3. 表格

### 3.1 每一行

```text
[序号] [时间输入框] [↤] [文本输入框] [✕]

序号      两位，仅显示
时间      mm:ss.xx；空 = 未打点；Enter 失焦提交
↤         把 MARK 写进这一行（需要先在波形上点一下）
文本      纯文本；Enter 在光标处拆成两行
✕         删除这一行
```

### 3.2 行选择

```text
点击行（非输入框）：
  普通点击    清空多选，选中该行
  Cmd/Ctrl    切换该行是否在多选里
  Shift       从当前行到该行整段多选
  选中带时间的行 → 同时 seek 到该行时间
```

```text
Shift + 在表格空白处按下拖动 → 框选（marquee）：
  经过的行加入多选；松开后 ESEL = 最大行号
输入框上不启动框选
```

### 3.3 改时间

```text
输入框 onchange：
  空         → t = null
  合法格式   → t = mm:ss.xx（四舍五入到 0.01）
  非法       → 提示"时间戳格式应为 mm:ss.xx"，恢复原值
每次合法修改前 snapshot()（可撤销）
```

### 3.4 改文本

```text
oninput：直接改 ERows[i].text，markDirty()（不 snapshot，见 §5）
onfocus：把 ESEL 设成该行
Enter：在光标处拆行
  左半留在本行；右半成为下一行（t=null）
  焦点移到新行行首
Backspace/Delete（光标在行首）：与上一行合并
  光标落在合并点；本行删除
```

### 3.5 粘贴

```text
在文本输入框里粘贴多行：
  按行拆开；形如 [mm:ss.xx]文本 的保留时间，其余 t=null
  插到当前行之后；焦点/选中落到最后一条

在表格空白处粘贴：
  插到 insertPos() 之后（最后一个多选行或当前行之后）
  同样解析时间戳
```

### 3.6 增删与全选

```text
加行：在 insertPos() 插入空行
      insertPos = 最后一个多选行+1；没有多选则当前行+1；再没有就末尾
删行：删多选；没有多选删当前行；全删光时保留一个空行
全选：所有行加入 SEL
```

### 3.7 从波形绑时间

```text
点击波形 → seekPrecise(点击时间)，并记 MARK
表格行点 ↤ → 该行 t = MARK，选中移到下一行
MARK 为空 → 提示"先在波形上点一个位置"
```

```text
这是打轴的主路径：
  播放/拖到大概位置 → 点波形 → ↤（下一行）→ 继续
```

## 4. 时间格式

```text
显示：lrcFmt(t)
  mm:ss.xx，两位分钟、两位秒、两位小数
  例：00:05.00、01:23.45
  t=null → 空字符串

解析：lrcParse(v)
  只接受 ^(\d+):(\d+(\.\d+)?)$
  秒可以带小数；结果四舍五入到 0.01
  非法 → null
```

```text
时间列不处理 offset：
  offset 是播放/显示时的整体偏移，表格里存的是"文件时间"。
```

## 5. 撤销、重做、脏标记

```text
snapshot()：把 EROWS 序列化进 UNDO，清空 REDO，markDirty()
undo()/redo()：栈之间搬 JSON，重新渲染
```

```text
哪些操作会 snapshot：
  改时间、拆行、合并行、粘贴多行、加行、删行、绑时间

哪些不会：
  文本输入（每个字符都 snapshot 会让撤销粒度碎成单字）
  → 文本编辑的撤销回到"上一次结构性操作"的状态
```

```text
markDirty()：
  EDIT_REVISION++
  EDIRTY = true
  savehint = "未保存…"
  重置 1.5 秒自动保存定时器
```

## 6. 保存

### 6.1 自动保存

```text
停止编辑 1.5 秒（ui.autosave_ms）→ saveLrc(silent=true)
```

```text
saveLrc：
  ① 没有歌 / 不在编辑模式 / 正在替换 → 直接返回
  ② 等上一次 SAVE_PENDING 结束（避免旧内容后写覆盖新内容）
  ③ 不脏且不是强制保存 → 返回
  ④ 记下 revision，POST /api/lrc {action:"save", uid, version, lines}
  ⑤ 成功且 revision 没变 → EDIRTY=false，savehint="已保存 HH:MM:SS"
  ⑥ 失败 → 保持 dirty，silent 时不弹 toast，只改 savehint
```

```text
为什么用 revision：
  保存请求发出后用户又改了字 → revision 变了 → 即使保存成功也不能清 dirty。
```

### 6.2 手动保存

```text
点「保存」：saveLrc(false, force=true)
  · 不管脏不脏都写一次
  · 表格为空 → 提示"没有歌词行"，不发请求
```

### 6.3 后端保存

```text
service.lrc save：
  ① 读当前文件，拿 metadata 和旧标注
  ② 按内容对齐旧标注到新行序（文本相同的行沿用读音）
  ③ 逐行决定：对齐到 → 沿用；没对齐 / 改字 → 重新注音
  ④ 锁内校验 version → 备份 → 临时文件 + os.replace 写 nhlrc
  ⑤ 没有非空歌词行 → 拒绝保存（不写空文件）
```

```text
所以表格式编辑器可以随便插入/删除/移动行：
  读音跟着文本走，不会整份丢。
```

### 6.4 保存提示

```text
savehint：
  未保存…        dirty
  已保存 12:34:56  成功
  保存失败        dirty
```

```text
自动保存成功不弹 toast（避免每次停顿都闪一下）；
手动保存失败、退出/切歌前保存失败才弹。
```

### 6.5 切歌 / 切模式前的保存

```text
load() 在编辑模式下：
  setLrcLocked(true) → flushLrc() → 取新歌
  flushLrc 失败 → 放弃切换，保留当前编辑
```

```text
setLrcLocked(true) 会先把焦点从表格移走（触发 change），再 inert，
避免"最后一个时间输入框还没提交就被锁住"。
```

## 7. 导入 / 导出 / 恢复

### 7.1 导入歌词

```text
选文件（pywebview pick_lrc_text）
  → confirm 覆盖当前歌词
  → replaceLrc({action:"import_lrc", uid, version, text})
```

```text
replaceLrc：
  LRC_REPLACING=true
  锁表格
  等 SAVE_PENDING 结束（防旧自动保存覆盖刚导入的内容）
  调接口 → 重新 openLrcEditor()
  解锁
```

```text
导入语义：
  · .lrc  → 只有正文
  · .nhlrc → 正文 + 读音
  · 原文件先备份成 .bak
```

### 7.2 导出

```text
点「导出」
  → POST /api/lrc {action:"export", uid, lines} 拿两种文本：
      nhlrc：正文 + 尾部
      lrc：只有正文
  → pywebview save_text(默认名 <歌名>.nhlrc, nhlrc, lrc)
  → 用户选 .lrc 扩展名 → 写纯 LRC；否则写 nhlrc
```

### 7.3 恢复最初

```text
点「恢复最初」
  → GET /api/lrc {action:"backup"} 查 .bak 是否存在/时间/行数
  → confirm 显示备份时间和行数
  → replaceLrc({action:"restore", uid, version})
```

```text
备份只在"首次覆盖前"生成：
  之后的保存不会刷新 .bak；"恢复最初"就是回到那次。
```

## 8. 锁定与并发

```text
LRC_LOCKED：
  切歌、导入、恢复、替换期间为 true
  表格 inert，读写操作提前 return

LRC_REPLACING：
  导入/恢复/选中候选期间为 true
  saveLrc 直接拒绝，避免把替换过程写回旧内容

SAVE_PENDING：
  同一时刻最多一个 save 请求
  后续保存等待它结束再读当前表格
```

```text
请求自增：
  LRC_OPEN_REQUEST  防止多次"进入编辑"的旧响应覆盖新状态
  LOAD_REQUEST      防止切歌中的旧载荷覆盖新歌
```

## 9. 键盘

```text
表格外（焦点不在输入框）：
  Enter              加一行
  Delete / Backspace 删选中行（或当前行）
  Cmd/Ctrl + A       全选
  Cmd/Ctrl + Z       撤销
  Cmd/Ctrl + Shift+Z 重做

文本输入框内：
  Enter              在光标处拆行
  行首 Backspace     与上一行合并
  其他键             正常输入

时间输入框内：
  Enter              失焦提交
```

```text
空格/方向键是播放器快捷键：
  焦点在输入框时不拦截，避免打字时触发播放/跳转。
```

## 10. 与其它功能的关系

```text
波形：只在 LRC 模式显示；点击记 MARK，行内 ↤ 绑时间
偏移：offset 不影响表格里的 t；只影响播放显示
全部重置：不在编辑器里，是顶栏按钮：
  清空该歌 nhlrc 尾部 → 重新载入 → 引擎按默认重新注音
读音编辑：不在 LRC 表格里做；退出打轴后到普通视图点候选
```

## 11. 已知限制

```text
① 元数据标签不可编辑
   只原样保留；要改 [ti:]/[ar:] 需要手改文件或导入新歌词

② 撤销不按字符
   文本输入不 snapshot；撤销回到上一次结构性操作

③ 多选只支持 Shift/Cmd 点击或 Shift+拖动框选
   不能拖拽行排序（排序请用剪切/粘贴或外部工具）

④ 时间精度 0.01 秒
   输入更细的小数会被四舍五入

⑤ 空文件保护
   全是空文本时不保存；全删光会保留一个空行

⑥ 自动保存是"停止输入 1.5 秒"
   持续输入时不会中途保存；崩溃仍可能丢最后一段
```

## 12. 代码地图与测试

| 职责 | 位置 |
|---|---|
| 表格状态/渲染/交互/保存/导入导出 | `static/20-editor.js` |
| 模式切换、载入编排 | `static/10-app.js` |
| 时间格式/显示 | `static/30-playback.js`（lrcFmt/lrcParse 也在 20） |
| 保存后端（对齐/注音/写盘） | `service/lrc.py` |
| 格式与对齐 | `core/lrc_doc.py` |
| 文件读写/备份 | `core/lrc_files.py` |

```text
测试：
  tests/lrc_editor.test.cjs    前端时间/保存/锁定逻辑
  tests/test_lyrics_store.py   保存对齐、空文件保护、全部重置
  tests/test_player_http.py    接口层保存/导出
```

## 10. 权威写入与禁用状态

```text
data/lyrics/*.nhlrc = 用户资产
data/cache/lyrics/  = 可重建缓存，只做单向回退
```

```text
打开歌曲、自动注音都不写 nhlrc；
只有保存、导入、pick、恢复备份、删除/禁用会改权威文件。
```

```text
每次写入：
  LRC.LOCK 覆盖读取旧文档、合并、备份和写入
  version 不一致 → 保留草稿，返回冲突，不覆盖
  同目录临时文件 + os.replace

没有 nhlrc 时 version = "none"（不是 null）；
删除后 version 变成 disabled 文档哈希，
旧草稿的 "none" 会被拒绝，不能重新启用歌词。
```

```text
删除歌词不再删除 nhlrc：
  原子写入 disabled 文档，备份保留。
  读取时 disabled 优先：
    不走缓存、不自动匹配
  保存新歌词、导入、pick、恢复备份会重新启用。

删除失败时不清 EDIRTY；
恢复/导入前先等自动保存结束，再读取当前 version。

删除和导入/恢复共用 LRC_REPLACING 切歌锁；
删除的迟到响应只有在当前仍是原曲时才允许改状态。
「全部重置」使用当前 load 得到的 version，不沿用上一首的；
重置响应还要校验发请求时的 LOAD_REQUEST，
如果已经发起切歌，迟到响应不能把页面拉回旧歌。
```

```text
save 请求带 version；
import_lrc / restore / delete 也带当前 version。
```
