# 打包

> 已配置 PyInstaller onedir，构建 thin / full 两种 `.app`。

> Intel / x86_64 支持计划见 [Intel Mac 支持](../新增功能文档/Intel Mac支持.md)。

## 0. 当前状态

```text
开发入口：
  make app
  .venv/bin/python -m momo_uta_app
```

```text
2026-11-28 v1.2.12 已重建：
  thin / full 两种 .app
  具体 commit / sha256 见 dist/VERSIONS.txt
  thin / full 两种 zip
  VERSIONS.txt（commit + sha256）
```

```text
已配置 PyInstaller onedir，两种 .app 都能构建：
  thin  薄壳版（外部 demucs / ffmpeg）
  full  完整版（内置 demucs + torch + ffmpeg）
```

```bash
./packaging/build.sh thin|full
```

```text
产物：
  dist/thin/momo-uta-thin.app   ~461 MB
  dist/full/momo-uta-full.app   ~1.7 GB
  dist/momo-uta-thin.zip        ~88 MB
  dist/momo-uta-full.zip        ~284 MB
  dist/VERSIONS.txt
```

thin / full 都随包：

```text
Frameworks/bin/soundstretch
Frameworks/bin/libSoundTouch.1.dylib
Resources/licenses/SoundTouch-LGPL-2.1.txt
```

full 另外随包 ffmpeg 和 `ffmpeg-GPLv3.txt`。  
第三方说明见 `THIRD_PARTY_NOTICES.md`。

原生音频 helper：

```text
Contents/Helpers/momo-audio
```

由 `native/momo-audio/build.sh` 编译，
`packaging/build.sh` 放入 app 并单独签名。

```text
当前为 ad-hoc 签名，未公证。
正式分发需要 Developer ID + notarization。
```

```text
不支持 wheel / pip 安装入口。
交付形态只有 macOS .app；wheel 不包含 config、static、tables、corpus。
pyproject 不注册 console script，避免安装出一个不可用的 momo-uta 命令。
```

### 两个版本

| 版本 | 文件 | 内容 | 体积 |
|---|---|---|---|
| thin | `momo-uta-thin.app` | 播放器 + 歌词 + LRC + 翻译 + 内置 SoundTouch；外部 demucs / ffmpeg | ~461 MB |
| full | `momo-uta-full.app` | thin + demucs + torch + ffmpeg | ~1.7 GB |

```text
两者共享同一份用户数据：
  ~/Library/Application Support/momo uta/data
```

```text
full 里的 demucs 通过 app 的 --momo-demucs 子命令运行；
入口先调用 multiprocessing.freeze_support()，避免子进程重开窗口。
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
src/momo_yomi
src/momo_player
src/momo_uta_app
config/defaults.json
static/player.html/.css/.js
data/tables/jmdict_*.json
data/curated/glossary_lyrics.json
data/curated/counters.json
data/curated/lyrics_exclude.json
data/corpus/ndl_reading_stats.json
assets/momo-uta-logo.icns
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
data/curated/      用户歌单/元数据/导入历史
                   （只有 glossary/counters/lyrics_exclude 默认表随包）
data/config.json   本机配置
data/cache/        可重建缓存
data/vocals/       人声缓存
data/sources/      原始素材
data/corpus/       语料统计（仅 ndl_reading_stats.json 随包）
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
full 会在构建时查找 ffmpeg：MOMO_FFMPEG、PATH、/opt/homebrew/bin、/usr/local/bin。
缺失时构建直接失败，不会生成缺 ffmpeg 的 full 包。
```

## 5. 体积

当前实际产物：

```text
thin.app    ~461 MB
full.app    ~1.7 GB
```

```text
thin.zip    ~88 MB
full.zip    ~284 MB
```

```text
zip 是 .app 的 --keepParent 压缩；
体积受文件系统块大小影响，du 会显示略大。
```

当前构建 sha256 见：

```text
dist/VERSIONS.txt
```

主要占用：

```text
Python 运行时       ~75 MB
Sudachi 词典        ~193 MB
PyObjC / pywebview  ~5–10 MB
JMDict 表           ~10 MB
应用/前端           ~1 MB
full 额外 torch/ffmpeg
```

```text
full 的体积主要来自 torch、torch 依赖和 ffmpeg。
```


## 6. 打包方式

已使用：

```text
PyInstaller onedir
  → .app
  → zip（当前）
  → DMG（未做）
```

```text
不用 onefile：
  启动解压慢
  调试困难
  资源路径更容易出错
```

## 7. 路径问题

```text
paths.BUNDLE
  = .app 内只读资源，来自 PyInstaller _MEIPASS

paths.ROOT
  = 可写用户目录
    ~/Library/Application Support/momo uta
    可用 MOMO_HOME 覆盖

开发时：
  BUNDLE = ROOT = 项目根
```

只读资源：

```text
config/defaults.json
data/tables
data/curated/glossary_lyrics.json
data/curated/counters.json
data/curated/lyrics_exclude.json
static
```

可写用户数据：

```text
data/curated
data/lyrics
data/cache
data/vocals
data/config.json
```

```text
首次启动由 paths.bootstrap() 建目录并复制默认表。
可写目录不能落到 .app 内部。
```

## 8. 菜单栏名称

```text
window title：桃歌
CFBundleName / CFBundleDisplayName：桃歌
```

```text
已写入 Info.plist，不在运行时改 AppKit 进程名。
```


## 9. 签名与公证

```text
默认：ad-hoc codesign
正式分发：MOMO_CODESIGN_IDENTITY + MOMO_NOTARY_PROFILE
```

```text
应用 entitlements：
  packaging/entitlements.plist

当前包含：
  com.apple.runningboard.assertions.webkit

用途：
  WebKit 后台媒体播放断言
  避免后台时 WebContent 被挂起导致无声

限制：
  这是 restricted entitlement
  ad-hoc 签名不能携带，否则 AMFI 拒绝启动
  只有 Developer ID 签名路径才会启用
```

```text
entitlements 同时写入：
  momo_uta.spec 的 BUNDLE
  build.sh 的最终 codesign
```

```bash
MOMO_CODESIGN_IDENTITY="Developer ID Application: ..." \
MOMO_NOTARY_PROFILE="momo-notary" \
./packaging/build.sh thin
```

```text
有 MOMO_CODESIGN_IDENTITY 时使用 hardened runtime + timestamp；
有 MOMO_NOTARY_PROFILE 时提交 notarytool 并 staple。
没有证书时仍是 ad-hoc 签名，只能本机/自用。
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
打开数据路径
全局热键
关闭窗口后台播放
Dock 重新显示
```

## 12. 已知未做

```text
1. 没有签名 / 公证
2. 没有 .dmg 构建脚本
3. 没有自动更新
4. thin 的外部 demucs / ffmpeg 需要用户自己安装
5. thin / full 共享同一份 Application Support 数据
6. 尚未做 Intel / universal2
7. 尚未做正式首启迁移
```

## 13. 相关

```text
architecture.md
cache.md
development.md
```
