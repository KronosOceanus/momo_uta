# seek precision bench

测当前 `AudioBufferSourceNode + playbackRate` 的 seek 基线。

不是 SoundTouch / Rubber Band 实时引擎的测试；后两者接入实时播放后，复用同一套 click track 和判定方法。

## 运行

```bash
cd experiments/seek-bench
python3 generate_click.py
python3 server.py
```

浏览器打开：

```text
http://127.0.0.1:8766/bench.html
```

点“开始测试”。

## 测什么

click track：

```text
12s
每 0.5s 一个 2ms 2kHz 脉冲
44.1kHz / 16-bit / mono
```

每个速度：

```text
1.00×
0.80×
0.65×
```

每个目标：

```text
1.03s
4.27s
7.51s
```

从目标位置 `start(0, target)`，捕捉输出中的下一个 click。

计算：

```text
expectedClick = 下一个 0.5s click
actualSource  = target + (capturedTime - startTime) * speed
error         = actualSource - expectedClick
```

## 结果含义

```text
error 基本恒定
  → 是输出链路延迟，不是 seek 偏移

error 随 target 增大
  → seek 映射有累积误差
```

`error` 用毫秒显示，同时表格保留“首次 click 输出”用于看延迟。

## 本次基线结果

在 WebKit / pywebview 环境，44.1kHz click track：

```text
1.00×  |error| median=11.97ms  p95=11.97ms  max=11.97ms
0.80×  |error| median=9.64ms   p95=9.65ms   max=9.65ms
0.65×  |error| median=7.91ms   p95=7.91ms   max=7.91ms
```

关键不是这个 12ms 本身，而是它**在所有 target 上恒定**：

```text
1.03s / 4.27s / 7.51s 的误差完全一样
误差随 speed 等比缩小
```

说明：

```text
seek 内容偏移 ≈ 0
约 12ms 是输出链路延迟
不是目标位置越远误差越大
```

因此这个基线可以表述为：

```text
当前 AudioBufferSourceNode 的 seek 对齐是采样级准确的；
观测到的约 12ms 是 WebKit 输出延迟，不是 seek 误差。
```

## DSP reset 实验

这一节才测 SoundTouch / Rubber Band 本身。

`seek_dsp.cpp` 模拟一次实时 seek：

```text
reset 引擎
→ 从目标源时间开始喂 click track
→ 收集输出
→ 找第一个 click
```

构建：

```bash
brew install sound-touch rubberband
cd experiments/seek-bench
./build_dsp.sh
./seek_dsp --input click.wav
```

### 结果

```text
1.00×
  SoundTouch      +1.13ms
  Rubber Band R3  +0.36ms

0.80×
  SoundTouch      -6.19 … -13.55ms
  Rubber Band R3  -9.52 … -9.82ms

0.65×
  SoundTouch      -11.51 … -25.44ms
  Rubber Band R3  -17.40 … -18.51ms
```

负数表示：

```text
检测到的第一个 click 在源时间轴上比预期更早
```

这不一定是“seek 偏移”，
也可能是 click 瞬态在时间拉伸里被提前/平滑/重复。

### 边界 / 采样率 / 0.5×

44.1kHz mono 和 48kHz stereo 的结果基本一致：

```text
0.80×  SoundTouch   -6.19 … -11.81ms
0.80×  Rubber Band  -9.15 … -10.10ms

0.65×  SoundTouch   -11.43 … -18.53ms
0.65×  Rubber Band  -16.31 … -18.43ms
```

0.5× 时 click 起音被拉得更明显：

```text
SoundTouch    -34 … -41ms
Rubber Band   -26ms
```

这说明慢速越极端，
“第一个 click 的位置”越不能直接等同于“seek 目标位置”；
需要看起音检测和瞬态处理。

### 处理耗时

同样处理约 3 秒输出：

```text
SoundTouch      约 4ms
Rubber Band R3  约 50–66ms
```

这是离线循环处理耗时，不是实时音频线程的 CPU 峰值。

### 说明

```text
测试的是 reset + 重新喂入后的算法输出
没有接 CoreAudio 输出设备
因此不包括硬件输出延迟
```

## 音高 / 谐波测试

纯音测试，目标不是听感，而是确认变速后基频是否保持。

```bash
cd experiments/seek-bench
../../.venv/bin/python dsp_quality.py
```

测试：

```text
440Hz / 220Hz / 110Hz
10 秒纯音
0.80× / 0.65×
```

结果：

```text
所有组合的基频偏差都在 ±0.12 cents 以内
```

例如：

```text
Rubber Band 440Hz 0.80×  → 440.000Hz  -0.00 cents
SoundTouch   440Hz 0.65×  → 439.970Hz  -0.12 cents
```

说明“保持原调”在纯音层面是成立的。

注意：

```text
THD 显示 0 只说明纯音几乎没有谐波
不代表真实音乐的人声/鼓点/瞬态质量
```

## 长片段吞吐测试

```bash
cd experiments/seek-bench
../../.venv/bin/python dsp_throughput.py \
  --input "$HOME/Music/网易云音乐/YOASOBI - たぶん.mp3" \
  --seconds 60 --speeds 0.8 0.65
```

60 秒真实歌曲：

| 引擎 | 速度 | 输出 | 处理 | 实时倍率 |
|---|---:|---:|---:|---:|
| Rubber Band R3 | 0.80× | 75.00s | 5.668s | 13.2× |
| SoundTouch | 0.80× | 75.00s | 0.244s | 307.0× |
| Rubber Band R3 | 0.65× | 92.31s | 10.045s | 9.2× |
| SoundTouch | 0.65× | 92.31s | 0.277s | 332.8× |

这是离线 CLI 吞吐，不是实时音频线程 CPU 峰值。

## 已知边界

```text
浏览器部分用 ScriptProcessor，已废弃但 WebKit 仍可用
浏览器部分不测真实扬声器延迟
DSP 部分是 reset + 重新喂入，不是 CoreAudio 实时输出
仍未测硬件输出延迟、实时 seek、seek 后爆音
```
