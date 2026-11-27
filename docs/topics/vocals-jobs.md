# 人声任务与 job

> 本文说明人声分离队列、任务生命周期、取消、缓存和清理。
> 人声缓存目录见 [cache](cache.md)。

## 0. 一句话

```text
job = 对外可见的任务生命周期
VOC = 人声分离执行器

job.state 管任务
job.stage 管人声真实阶段
```

## 1. 触发时机

```text
普通歌词页
  → /api/song 只同步 vocals 状态
  → 不创建 job

进入 LRC 编辑模式
  → openLrcEditor(entering=true)
  → startVocals(uid)

已有 done / running
  → 不重复创建
```

```text
普通页切歌只更新状态；
LRC 编辑模式切歌会回到普通页，不触发。
```

## 2. 两层结构

```text
service.jobs
  → core.jobs（job 表）
  → core.vocals（队列 + worker + 子进程）
```

```text
core.jobs 不执行 demucs。
core.vocals 不知道 HTTP。
```

## 3. job.state

```text
queued
running
canceling
done
failed
canceled
```

```text
queued      job 线程已建立，业务还没完成
running     job 线程正在等/执行
canceling   已请求取消，等待执行器结束
done        成功
failed      异常
canceled    取消完成
```

## 4. job.stage

```text
stage = 执行器真实阶段
```

人声任务：

```text
job.state=running
job.stage=queued | running | canceling
```

原因：

```text
VOC 队列可能还没轮到这首歌，
job 线程已经在等它。
```

```text
所以不能只看 job.state 说“demucs 正在跑”。
前端列表显示 stage。
```

## 5. VOC 队列

```text
core.vocals.ensure(uid, audio)
```

```text
已有 meta
  → 直接返回 done

已有 queued/running/canceling
  → 返回同一任务

否则
  → _states[uid] = queued
  → 放进串行 Queue
  → 启动 worker
```

```text
同一 uid 幂等，不会重复排队。
```

## 6. 执行流程

```text
worker:
  dequeue
  → 检查 queued 超时
  → 状态 running
  → demucs --two-stems=vocals
  → ffmpeg 转 16k 单声道
  → analyze()
  → 写 meta.json
  → 纯音乐删除 vocals.wav
```

```text
全程串行，一条一条跑。
```

## 7. demucs / ffmpeg 子进程

```text
POSIX:
  start_new_session=True
  独立进程组
  超时/取消 → killpg(SIGKILL)
```

```text
子进程超时：
  run_timeout_s 默认 600
  杀整组，包含辅助进程
```

```text
HF 端点默认走 hf-mirror.com。
```

## 8. 超时

```text
queue_timeout_s
  排队阶段超时：worker 真正取到任务时检查

run_timeout_s
  单次 demucs / ffmpeg 子进程超时
```

```text
超时写 failed，原因保留在 state/error。
```

## 9. 取消

```text
cancel(uid)
```

queued：

```text
直接标 canceled
不会进入 demucs
```

running：

```text
状态 canceling
kill 进程组
worker 清临时目录
最终 canceled
```

```text
canceling 时按钮禁用。
```

```text
单曲取消 / 全部取消都只作用于 vocals，
不影响 match / rebuild。
```

## 10. job 取消与 VOC 取消

```text
POST /api/jobs/<id>/cancel
  → service.jobs.cancel_job
  → core.jobs.cancel
  → _cancel_requested=True
  → state=canceling
  → 调 VOC.cancel
```

```text
job.cancel 是入口；
VOC.cancel 是执行器动作。
```

## 11. 结果与失败

```text
成功：
  meta.json 写入
  job done

失败：
  meta 不写
  job failed
  错误字符串截断保留
```

```text
纯音乐：
  has_vocals=false
  删除 vocals.wav
  保留 meta.json
```

## 12. VAD 结果

```text
16k 单声道
20ms 帧
RMS 统计
floor = 10% 分位
threshold = max(floor*floor_mult, abs_threshold)
ratio = 超阈值帧占比
has_vocals = ratio >= ratio_min
```

```text
只是“有没有人声”的判断，
不是高精度 VAD。
```

## 13. 缓存布局

```text
data/vocals/<uid>/vocals.wav
data/vocals/<uid>/meta.json
data/tmp/vocals/<uid>-<pid>-<ms>/
```

```text
数据 vocals：
  可重算，但很贵
  LRU + max_bytes
```

## 14. 清理

```text
cleanup(protected, max_bytes)
```

```text
启动时清理孤儿 tmp
所有有效 vocals 都保留
超过 max_bytes(默认 2GB) 按 last_used 淘汰
淘汰时先清未 protected，再清 protected
queued/running/canceling 跳过
```

```text
纯音乐只有 meta 也是有效缓存。
```

## 15. API

```text
GET  /api/jobs/active
GET  /api/jobs/<id>
POST /api/jobs
POST /api/jobs/<id>/cancel
POST /api/jobs/cancel_all
```

```text
kind = vocals | match | rebuild
```

```text
人声取消只接受 vocals。
```

## 16. 已知限制

```text
1. 人声串行，没有优先级。
2. 没有切歌自动取消。
3. 没有实时进度条，只有 state/stage。
4. 队列超时在出队时检查，不是排队计时器。
5. cleanup 对非 protected 缓存较激进。
6. 依赖 demucs / ffmpeg 外部环境。
```

## 17. 相关

```text
cache.md
player-state.md
```
