# 打包

> 当前还没有正式 `.app` 打包配置。本文记录目标、依赖、体积和待办。

## 0. 当前状态

```text
开发入口：
  make app
  .venv/bin/python -m nihonco_player_app
```

```text
正式 .app：
  尚未配置 PyInstaller / py2app
  尚未签名 / 公证
```

## 1. 运行结构

```text
Python 进程
  ├─ ThreadingHTTPServer（随机端口）
  ├─ pywebview 窗口
  ├─ WebAudio 前端
  └─ 全局热键（Carbon）
```

```text
音频、HTML、CSS、JS 都在本机。
不依赖外部服务启动。
```

## 2. 必须打包

```text
Python 运行时
src/nihonco_yomi
src/nihonco_player
src/nihonco_player_app
config/defaults.json
static/player.html/.css/.js
data/tables/jmdict_*.json
```

```text
pywebview
pyobjc-core
pyobjc-framework-Cocoa
SudachiPy
sudachidict_core
mutagen
```

## 3. 不能打包

```text
data/lyrics/       用户歌词资产
data/curated/      歌单/元数据/导入历史
data/config.json   本机配置
data/cache/        可重建缓存
data/vocals/       人声缓存
data/sources/      原始素材
data/corpus/       语料统计
eval/              评测资产
```

```text
首次启动时创建用户数据目录。
```

## 4. 可选依赖

```text
demucs
torch
ffmpeg
```

```text
demucs / torch 是包体大头。
ffmpeg 是外部二进制，需要单独处理。
```

## 5. 体积估算

基础版（不含人声分离）：

```text
.app 解压后  约 300–400 MB
.dmg 压缩后  约 150–220 MB
```

主要占用：

```text
Python 运行时       ~75 MB
Sudachi 词典        ~193 MB
PyObjC / pywebview  ~5–10 MB
JMDict 表           ~10 MB
应用/前端           ~1 MB
```

完整版（带 demucs）：

```text
.app 解压后  约 1.0–1.3 GB
.dmg 压缩后  约 500–800 MB
```

```text
torch 约 626 MB，是主要变量。
以上是估算，实际以 PyInstaller 产物为准。
```

## 6. 打包方式

建议：

```text
PyInstaller onedir
  → .app
  → 外层 DMG
```

```text
不用 onefile：
  启动解压慢
  调试困难
  资源路径更容易出错
```

## 7. 路径问题

```text
代码通过 nihonco_yomi.paths 计算 ROOT。
打包后 ROOT 不能指向临时解压目录。
```

需要区分：

```text
只读资源：
  config/defaults.json
  data/tables
  static

可写用户数据：
  data/curated
  data/lyrics
  data/cache
  data/vocals
  data/config.json
```

```text
打包时要让可写目录落到用户可写位置，
不能写进 .app 内部。
```

## 8. 菜单栏名称

```text
window title 已经是 nihonco uta
系统菜单栏仍可能显示 Python
```

正式修法：

```text
打包 .app
CFBundleName / CFBundleDisplayName = nihonco uta
```

```text
不做运行时 AppKit 改进程名的临时方案。
```

## 9. 签名与公证

```text
codesign
notarytool
staple
```

```text
需要 Developer ID 证书。
没有公证的 .app 在其他机器会被 Gatekeeper 拦。
```

```text
全局热键用 Carbon 系统框架，不需要 Accessibility。
```

## 10. 前端资源

```text
static/ 直接随包
不经过 Vite/Webpack
__CFG 由服务端注入
```

```text
不能把 page.html 当静态文件直接打开：
  需要 __CFG
  需要本机 HTTP 服务
```

## 11. 打包后要验证

```text
启动
打开窗口
扫描曲库
播放音频
打开 LRC
保存 nhlrc
导入
切换主题
全局热键
关闭窗口后台播放
Dock 重新显示
```

## 12. 已知未做

```text
1. 没有 PyInstaller spec
2. 没有资源拷贝规则
3. 没有用户数据目录重定向
4. 没有签名/公证
5. 没有自动更新
6. 没有 .dmg 构建脚本
7. demucs/torch 是否随包未定
8. ffmpeg 分发未定
```

## 13. 相关

```text
architecture.md
cache.md
development.md
```
