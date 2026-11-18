# 文档索引

| 文档 | 内容 | 什么时候看 |
|---|---|---|
| [`../README.md`](../README.md) | **标注引擎设计**：三支柱、四档判定、契约、架构、表清单 | 想理解引擎"为什么这么设计" |
| [`architecture.md`](architecture.md) | **架构**：三层边界、依赖规则、数据流、扩展点、迁移计划 | 改代码前先看这里 |
| [`player.md`](player.md) | **播放器现状**：歌单、播放、偏移、界面结构、接口、数据文件 | 改播放器 / 想知道某个按钮怎么工作 |
| [`lrc-editor.md`](lrc-editor.md) | **LRC 编辑器**：设计 + 已实现情况（波形、表格、打点、保存） | 做打轴功能时 |
| [`eval.md`](eval.md) | **评测**：数据集、跑分、基线数字（唯一出处）、指标定义、分层规则 R1–R12 | 想知道"现在多少分、怎么复现" |
| [`testing.md`](testing.md) | **测试**：93 条分五组、怎么写新测试、没覆盖什么 | 改代码前 |
| [`NOTES.md`](NOTES.md) | **开发笔记**：决策、死胡同、负结果、指标历史、踩坑记录 | 想重试某个思路前（先看是否已失败过） |
| [`../TODO.md`](../TODO.md) | 待做清单：功能 + 优化 | 决定下一步做什么 |

## 阅读顺序建议

```text
第一次接触     README「一页摘要」→ docs/eval.md
要动手改       docs/testing.md → player.md（或 lrc-editor.md）→ NOTES 相关小节
要判断可行性   docs/NOTES.md（失败过的思路都带数字，避免重复试错）
```

## 一句话分工

```text
README    引擎设计
player    播放器现状
lrc-editor 打轴工具
eval      评测与基线
testing   测试与回归
NOTES     历史与教训
TODO      接下来
```
