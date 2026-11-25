# SoundTouch vs Rubber Band

独立离线实验，不接入 momo uta 播放引擎。

目的：在同一段音频、同一速度下比较：

```text
处理耗时
CPU
输出时长
人声 / 鼓点 / 贝斯 / 瞬态的听感
```

## 依赖

```bash
brew install ffmpeg rubberband sound-touch
```

确认：

```bash
ffmpeg -version
rubberband --version
soundstretch 2>&1 | head
```

## 运行

```bash
.venv/bin/python experiments/time-stretch/run.py \
  --input "$HOME/Music/网易云音乐/YOASOBI - たぶん.mp3" \
  --start 30 \
  --seconds 20 \
  --speeds 0.8 0.65
```

生成：

```text
experiments/time-stretch/out/original.wav
experiments/time-stretch/out/rubberband-0.80.wav
experiments/time-stretch/out/soundtouch-0.80.wav
experiments/time-stretch/out/rubberband-0.65.wav
experiments/time-stretch/out/soundtouch-0.65.wav
experiments/time-stretch/report.html
experiments/time-stretch/metrics.json
```

用浏览器打开：

```text
experiments/time-stretch/report.html
```

## 本次样本

```text
源：YOASOBI - たぶん
片段：30.0s 起，20.0s
格式：44.1kHz / 立体声 / PCM 16-bit
```

实测：

| 引擎 | 速度 | 输出时长 | 处理耗时 | 实时倍率 | CPU |
|---|---:|---:|---:|---:|---:|
| Rubber Band R3 | 0.80× | 25.000s | 2.672s | 9.36× | 1.751s |
| SoundTouch | 0.80× | 25.000s | 0.084s | 297.00× | 0.082s |
| Rubber Band R3 | 0.65× | 30.769s | 2.374s | 12.96× | 2.365s |
| SoundTouch | 0.65× | 30.769s | 0.094s | 328.60× | 0.092s |

## 注意

```text
这是离线处理，不测实时 seek。
seek 要在接入实时引擎后，单独测：
  点击到出声延迟
  seek 后相位恢复
  seek 精度
  CPU 峰值
```

```text
SoundTouch 的 LGPL 和 Rubber Band 的 GPL 是两套不同许可证。
本实验不改变 momo uta 的许可证。
```

生成音频不提交仓库，`report.html` 和 `metrics.json` 也不提交。
