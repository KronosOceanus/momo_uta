# yomi：标注引擎实现

> 读者：要改引擎的人（加规则、调阈值、换分词器、查"为什么这里空着"）。
> 定位：**实现文档，自成一体**。术语、数据结构、判定规则、命令都在本文内；
> 不依赖任何其它文档，照着从头读就能把引擎跑起来。
>
> 代码位置：`src/nihonco_yomi/`。文中引用函数名，不写行号（行号会漂）。

## 0. 三十秒版本

```text
它做的事：输入一句日文，给每个汉字标上读音（振假名），
          再顺带生成整句的罗马音和 IME 键位。

输入： "今日は雨が降る"
输出： 今日(きょう) は 雨(あめ) が 降(ふ)る
       romaji: kyou wa ame ga furu
       keys:   kyou ha ame ga furu
```

```bash
python -m nihonco_yomi.annotate --text "今日は雨が降る" --layers ruby,romaji,keys
```

```text
读法约定（后文反复用到）：
  segment   一个片段：连续的原文 + 可选读音（今日 / きょう）
  ruby      片段上的假名读音
  level     这个读音有多可信：A / AB / B / C / K
  K         纯假名片段（は、が、る），本来就不需要注音
  C         弃权：没有可靠读音，宁可不标
```

## 1. 定位与边界

```text
输入    一段日文（可多行），可选：要哪些层、LLM 开关、emit 档位
输出    逐行的 segments（base + ruby + 档位 + 区间）+ 可选的 romaji / keys 层 + 统计
```

```text
做：
  · 分词、切段、查表、给读音
  · 给每个片段定档（A / AB / B / C / K），该弃权就弃权
  · 生成罗马音层、IME 键位层
  · 输出前用不变量自检

不做：
  · 不联网、不读写歌单、不开 HTTP 服务
  · 不做上下文语义消歧（那是 LLM 补丁的职责，默认关闭）
  · 不负责渲染成 HTML（render.py 只服务于播放器）
```

```text
为什么保持纯计算：
  同一份输入必须得到同一份输出，评测才能复现；
  播放器、评测、演示页三处共用，不能各自夹带 IO 行为。
```

## 2. 模块地图

```text
src/nihonco_yomi/
├── __init__.py      对外接口：Annotator 类 / annotate() 函数 / overrides
├── annotate.py      主流程：分词、切段、查表、定档、政策、校验、组装
├── counters.py      量词与数字读音（一人、二羽、33、四つ…）
├── invariants.py    8 条不变量，违反即弃权
├── romaji.py        假名 → 罗马音 / IME 键位（两套规则，不能混用）
├── render.py        片段 → HTML（播放器使用）
├── llm.py           LLM 消歧客户端（只从候选里选，不生成）
├── kana.py          片假名 → 平假名
├── common.py        路径常量（ROOT / TABLES / CURATED / CORPUS / CACHE）
├── thresholds.py    A/AB/B 判档的全部数字
├── config.py        运行配置（非阈值类开关）
├── paths.py         运行期路径（CACHE 等）
```

```text
依赖方向：
  __init__ → annotate → {counters, invariants, romaji, kana, thresholds}
  render 只依赖 segments 结构，不依赖 annotate
  llm 只被 annotate 的可选分支调用
  任何模块都不 import nihonco_player*（scripts/check_arch.py 强制）
```

## 3. 数据表与词表

### 3.1 四张 JMdict 表（`data/tables/`，由 `tools/build/build_tables.py` 生成）

| 文件 | 内容 | 谁用 | 缺了会怎样 |
|---|---|---|---|
| `jmdict_heteronym.json` | 多音词 → 读音集合（约 3614 条） | 判定：命中就不给 A | `load_tables` 直接报错 |
| `jmdict_candidates.json` | 所有 ≥2 读音的词 → 候选 | 候选展示、LLM 候选 | 可缺（候选变少） |
| `jmdict_readings.json` | 词 → 读音 | `--llm` 才载 | LLM 候选缺失 |
| `jmdict_common_readings.json` | 常用读音（排序用） | `--llm` 才载 | 候选排序退化 |

```text
两类表不要混：
  判定用（heteronym）—— 每次都载，缺了必须报错（缺表会让规则静默失效，输出看起来却正常）
  候选用（readings / common / candidates）—— 只有开 LLM 时才需要
```

### 3.2 两张人工表（`data/curated/`，进仓库）

```text
glossary_lyrics.json   人工确认的读音（按"{词}"整词钉死）
  · 只为 J-Pop 歌词调过：私→わたし、何時→なんじ 这类
  · 换领域（商务/古典）要另建一张，不要改这张
  · 命中后直接 A 档，source=forced

counters.json          助数詞与数字读音表
  · NUM_TSITSU（一つ…十）
  · NUM_NIN（一人・二人・四人）
  · 数字读法由 counters 模块的规则计算（33 → さんじゅうさん），不是查表
```

### 3.3 语料统计（`data/corpus/ndl_reading_stats.json`）

```text
结构：  key → {n, top, share, dist{r: count}}
来源：  tools/build/build_corpus_stats.py（读 data/sources 下的歌词/语料）
用途：  A/AB/B 判档的核心证据；候选排序也按 dist 的次数
缺表：  不报错，但所有词退化成"词典单读音/多音词"两档（评测会明显掉）
```

## 4. 一次标注的流水线

```text
annotate(req)
  └─ 对每一行：annotate_line(line, options)
       ① get_tagger()                 Sudachi（mode A）分词，跳过零长 token
       ② annotate_token(w, …)         每个 token → 若干 segment
            · split_pieces()          汉字核心 + 假名前后缀，DP 切分
            · 数字/量词                计数器表优先（一人、四つ、33）
            · _word_decision()        这个读音从哪来（词典/人工/数字/OOV/专名）
            · assign_level()          唯一的定档点
            · candidates_for()        B 档才附候选（最多 8 个）
       ③ counters.merge_counters()    量词合并（跨 token 的显式合并）
       ④ apply_llm()                  可选：B 档用 LLM 缓存里的选择替换读音
       ⑤ 政策层 emit                  只决定"输出到哪一档"，不改判定
       ⑥ invariants.check_line()      I1–I8；违反 → 该段降为 C 并记原因
  └─ add_reading_layers()              生成 romaji / keys（按词分组、标点拼装）
  └─ 汇总 stats                        segments / annotated / coverage
```

### 4.1 切段：`split_pieces`

```text
目标：ruby 只覆盖"汉字部分"，送り仮名留在 base 里
      食べる → [食|た] + [べる]
做法：把词面切成 汉字块 / 假名块 / 其他，用 DP 找一个"恰好消耗完整读音"的切法
      假名块必须逐字对上；汉字块至少吃 1 个音节，最多 4×汉字数

为什么不能贪心：
  恋煩い(こいわずらい) 里「い」出现两次，贪心会切出 (恋煩,こ) 并把 わずら 丢掉
  → 读音看着对、对齐全错，这是最难发现的失败

返回 None = 对不上 → 该 token 尝试备用读音（feat[9]）→ 再尝试把 ー 还原成假名
            → 仍失败则整 token 弃权（reason=alignment_failed）
```

### 4.2 判定来源：`_word_decision`

```text
source      含义                                   档位（assign_level）
forced      人工词表命中                             A
counter     助数詞/数字表命中                        A
dict        词典读音（含语料证据）                  由统计决定 A / AB / B
numeral     surface 全是数字                         B（读音取决于后接量词）
proper      固有名詞                               B（读音不可推）
oov_marked  OOV 且 oov_mode=mark                    B
abstain     OOV 且 oov_mode=abstain                C（整词都不标）
```

```text
弃权理由（reason.code）：
  oov               词表里没有
  no_reading        分词器没给读音
  alignment_failed  送り仮名对不上
  invariant_failed  不变量没通过（detail 带 I 编号）
  其他              token 与原文不一致 / 未接入分词器（m0）
```

### 4.3 定档：`assign_level`

```text
唯一判定点。依据优先级（从高到低）：

source=forced/counter                     → A
source=proper/numeral/oov_marked          → B
有语料统计且 n ≥ MIN_CORPUS_N(20)：
    share ≥ SINGLE_READING_SHARE(0.99)    → A  「语料单读」
    选的读音 == / 前缀包含语料主读          → AB 「与语料主读一致」
    否则                                   → B  「与语料主读不符」
无语料统计：
    key 在 heteronym 表                     → B  「多音字（无语料证据）」
    否则                                    → A  「词典单读音」
```

### 4.4 真实例子：`今日は雨が降る`

```text
base   ruby   level  start end  word  basis
今日   きょう  AB     0     2     0    与语料主读一致（きょう, n=1177）
は     —      K      2     3     1
雨     あめ    A      3     4     2    词典单读音
が     —      K      4     5     3
降     ふ      AB     5     6     4    与语料主读一致（ふる, n=350）
る     —      K      6     7     4

romaji  kyou wa ame ga furu
keys    kyou ha ame ga furu        ← 助詞 は 在键位层是 ha，在罗马音层是 wa
stats   {segments: 6, annotated: 3, coverage: 0.5}
```

### 4.5 罗马音 / 键位：`add_reading_layers`

```text
分组规则（先分词、再分组、最后拼行）：
  同 word 的片段合成一组
  助動詞贴前一个谓语（生きてる → ikiteru）；でしょう/だろう 等不贴
  接頭辞（お/ご）贴后词（お願い → onegai）
  以 っ 结尾/开头的组跨组并入（叠辅音要看下一个假名）

拼行规则：
  开括号贴后词，闭括号与句末标点贴前词，句末标点后加空格
  助詞按 POS 判：只有 POS 带「助詞」的 は/へ/を 才读 wa/e/o
```

```text
两套规则不能混：
  罗马音  唱歌用：は→wa、を→o、長音→同元音、っ→叠辅音
  键位    IME 用：は→ha、を→wo、ー→-、ん在元音前→n'
```

## 5. 档位系统

```text
A    高置信：人工确认 / 语料单读 / 词典单音
AB   较可信：多读但选的是语料主读
B    不确定：多读且无语料 / 专名 / 数词 / OOV(mark)
C    弃权：没有可靠读音（ruby 为空，reason 说明原因）
K    纯假名片段（本来就不需要注音）
```

```text
三个开关（都不是判定，而是"输出政策"）：
  emit      A | AB | B    只输出到这一档；被压掉的片段 ruby=null, suppressed=true
  oov_mode  abstain | mark  OOV 是弃权还是标 B
  keep_ruby true/false     弃权片段是否带 would_be（评测统计用）
```

```text
改档位定义 = 改 thresholds.py 的数字
  MIN_CORPUS_N = 20
  SINGLE_READING_SHARE = 0.99
改完必须重跑：make stats + 三套歌词集（dev / test / gen），否则评测数字不可比
```

## 6. 数据结构

### 6.1 请求 / 响应

```json
// 请求
{"text": "今日は雨が降る", "layers": ["ruby", "romaji", "keys"]}
```

```json
// 响应（字段顺序可能不同）
{
  "version": {"engine": "sudachi", "dict": "sudachidict_core", "service": "0.3.0"},
  "lines": [{
    "text": "今日は雨が降る",
    "segments": [
      {"base": "今日", "ruby": "きょう", "level": "AB", "start": 0, "end": 2,
       "word": 0, "source": "dict", "basis": "与语料主读一致（きょう, n=1177）"},
      {"base": "は", "ruby": null, "level": "K", "start": 2, "end": 3, "word": 1},
      {"base": "雨", "ruby": "あめ", "level": "A", "start": 3, "end": 4,
       "word": 2, "source": "dict", "basis": "词典单读音"}
    ]
  }],
  "romaji": {"lines": ["kyou wa ame ga furu"], "text": "kyou wa ame ga furu"},
  "keys":   {"lines": ["kyou ha ame ga furu"], "text": "kyou ha ame ga furu"},
  "stats":  {"segments": 6, "annotated": 3, "coverage": 0.5}
}
```

### 6.2 segment 字段

| 字段 | 含义 | 谁用 |
|---|---|---|
| `base` | 原文片段（必须等于 `line[start:end]`） | 渲染、校验 |
| `ruby` | 平假名读音；空 = 不注音 | 渲染 |
| `level` | A / AB / B / C / K | 渲染颜色、评测 |
| `start` / `end` | 原文区间（字符下标） | 点击改读音、校验 |
| `word` | 词序号（同词片段共享） | 改读音、罗马音分组 |
| `wordbase` | 整词原形（仅多候选时给） | 候选面板按词聚合 |
| `source` | 读音来源（dict/forced/counter/…） | 诊断 |
| `basis` | 人话理由（"语料单读 100%（n=1177）"） | 诊断、悬停 |
| `cands` | 候选读音（B 档，≤8，实际选的排第一） | 候选面板 |
| `cand_parts` | 候选按片段切开后的读音 | 前端逐片替换 |
| `reason` | 弃权原因 `{code, label, detail?}` | 诊断 |
| `suppressed` | 被 emit 压掉 | 诊断 |

### 6.3 overrides（改读音）

```python
an.annotate("今日は", overrides={"w:今日": "こんにち"})   # 该词所有出现
an.annotate("赤い花", overrides={"o:0-0": "あか"})        # 第 0 行第 0 个词
```

```text
值必须是平假名。整词读音会再用 split_pieces 切回各片段（赤ん坊 → あか/ぼう）。
改完会重算该行 romaji / keys，不会留下旧值。
```

## 7. 不变量（一票否决）

```text
原则：违反不是"修正"，是"拒绝输出"——该段降为 C，并记 reason=invariant_failed。
```

| 编号 | 检查什么 | 说明 |
|---|---|---|
| I1 | 往返一致 | `line[start:end] == base` |
| I2 | 单调有序 | start/end 递增、不重叠 |
| I3 | 读音只含假名 | 平假名 + ー |
| I4 | 送り仮名一致 | 由 `split_pieces` 的 DP 保证（读音必须被完整消耗），输出层不复查 |
| I5 | 纯假名不得有 ruby | 数字/数词例外（8→はち 是有意的） |
| I6 | 助詞・助動詞不得被 ruby 覆盖 | 单字助詞 |
| I7 | 摩拉数 sanity | `汉字数 ≤ 读音长度 ≤ 4×汉字数` |
| I8 | 跨 token 必须显式 | 同片段覆盖多个 word → 只有助数詞合并是合法的 |

```text
I8 的例外：counters.merge_counters 会显式把跨 token 的片段写成同一个 word，
所以 I8 实质上是在抓"没声明就跨"的情况。
```

## 8. 接口与运行

### 8.1 Python

```python
from nihonco_yomi import Annotator

an = Annotator()                          # 载表一次，进程内复用
r = an.annotate("今日は雨が降る")
r["lines"][0]["segments"]                 # 片段
r["romaji"]["text"]                       # "kyou wa ame ga furu"
an.reading("今日は")                       # 整段假名读音
an.annotate_lines("…")                    # 只要 lines
```

```text
模块级 annotate(text) 是懒加载的便捷入口（全局单例）。
Annotator(llm=False, emit="B", layers=[...]) 控制开关。
```

### 8.2 命令行

| 参数 | 作用 |
|---|---|
| `--text "…"` | 标一段，打印 JSON |
| `--stdio` | NDJSON 协议：一行请求一行响应（评测用） |
| `--layers ruby,romaji,keys` | 要生成哪些层 |
| `--emit A\|AB\|B` | 只输出到这一档 |
| `--oov-mode abstain\|mark` | OOV 处理方式 |
| `--llm` / `--llm-min-conf` | 用 LLM 缓存覆盖 B 档 |
| `--keep-ruby` | 弃权片段附 would_be（统计用） |
| `--disable …` | 诊断：关掉 glossary / heteronym / counters |
| `--check-tables` | 打印各表条目数后退出 |

**stdio 协议（评测与外部集成用）**
```text
stdin   每行一个 JSON：{"text": "...", "layers": ["ruby"], "options": {}}
stdout  每行一个 JSON：正常响应，或 {"error": "..."}
启动时先 load_tables + 预热分词器，避免第一行超时
```

## 9. 测试与评测

```text
tests/test_annotate.py     切段、定档、候选、overrides、数字、专名
tests/test_invariants.py   I1–I8 各自的反例
tests/test_romaji.py       罗马音 vs 键位（は/を/ん/っ/長音）
tests/test_tables.py       表条目数与抽样（防表坏/空）
tests/test_api.py          HTTP 接口层（经 service）
```

```text
评测入口（tools/eval/evalkit.py）：
  make eval-dummy     冒烟
  make eval-real      开发集（含拉丁）
  make eval-test      测试集（不调参）
  make stats          重建语料统计
  make gold-audit     人工抽查金标
```

```text
纪律：thresholds.py 的数字和评测强绑定。改数字 → 重跑 stats + 三套歌词集，
      并记录新的基线数字（同一份评测集前后对比，否则数字不可比）。
```

## 10. 已知边界与常见坑

```text
① 分词器边界决定一切
   Sudachi 切错 → 整行可能弃权（reason=token 与原文不一致 / alignment_failed）
   换分词器/词典要重跑评测，不要只看单句效果

② 专名、数词默认不保证
   专名 B（读音不可推），数词 B（读音取决于后接量词），OOV 默认 C
   想"至少给个音"就开 --oov-mode mark 或用 LLM

③ 当て字 / 外来语 / 人名
   split_pieces 依赖读音与字面的假名对齐；对不齐就弃权，不猜

④ 人工词表是"歌词领域"的
   glossary_lyrics.json 里 私→わたし 只对歌词成立
   换领域请另建表，不要改这张

⑤ LLM 只做"从候选里选"
   不许生成候选外的读音；置信度低于阈值照旧 B
   开发集实测 B 档 73.2% → 80.7%（数字随评测集变化，不是接口承诺）；A 档不许碰

⑥ emit 不是"提高准确率"
   它只是"少输出不确定的"，会让 coverage 下降、A 档覆盖率上升

⑦ 不变量是为了"不误导"
   宁可空着（C），也不给一个看起来对、实际错的读音
```

## 11. 代码阅读路线（建议顺序）

```text
1 __init__.py::Annotator.annotate      看输入输出与 overrides
2 annotate.py::annotate_line           看一行怎么串起来
3 annotate.py::annotate_token          看一个词怎么切、怎么判定
4 annotate.py::split_pieces            DP 对齐（最容易改错的地方）
5 annotate.py::assign_level            唯一的档位判定
6 annotate.py::add_reading_layers      罗马音/键位分组与拼行
7 invariants.py::check                 输出闸门
8 thresholds.py                        数字都在这里
```

## 12. 附录：术语表

| 词 | 意思 |
|---|---|
| segment | 一个片段：连续的原文 + 可选读音 |
| 送り仮名 | 词尾假名（食べる 的 べる） |
| 摩拉 | 日语音节单位（きょ = 1 摩拉） |
| 多音词 / 多音字 | 同一个词面有多个读音（今日：きょう/こんにち） |
| OOV | 分词器词表里没有的词 |
| 弃权 | 不给读音，level=C，reason 说明原因 |
| emit | 输出政策：只到某一档为止 |
| 档位 | A/AB/B/C/K，表示"这个读音有多可信" |
| forced | 人工词表钉死的读音 |
