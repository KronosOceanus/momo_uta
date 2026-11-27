# Intel Mac 支持

> 状态：未构建、未发布。当前发布包只有 arm64。
> 目标：在 Intel Mac 上提供 x86_64 thin 包；full 包取决于 PyTorch 的 Intel wheel。

## 1. 目标范围

```text
架构        x86_64
最低系统    macOS 12 Monterey
机型        约 2015 年以后、能升级 Monterey 的 Intel Mac
```

当前 `packaging/momo_uta.spec` 写死：

```python
target_arch="arm64"
```

以及：

```text
LSMinimumSystemVersion = 12.0
```

所以不能只把 `target_arch` 改成 `x86_64`，  
Python、原生扩展和外部工具也必须是 x86_64。

## 2. 两种支持范围

```text
thin Intel
  可行
  soundstretch / libSoundTouch 内置
  ffmpeg / demucs 由用户外部安装

full Intel
  有条件
  必须确认 torch / torchaudio 仍有 macOS x86_64 wheel
  即使可用，CPU 人声分离也会很慢
```

第一版建议只承诺：

```text
Intel thin
```

不要对 Intel full 做承诺，除非在真实 Intel 机器上完成验证。

## 3. 原生依赖

以下所有组件必须是 x86_64：

```text
Python
pyobjc-core / pyobjc-framework-Cocoa
sudachipy
numpy
soundstretch
libSoundTouch.1.dylib
ffmpeg（full，或用户外部安装）
torch / torchaudio（full）
```

检查方式：

```bash
file /path/to/binary
lipo -archs /path/to/binary
```

期望：

```text
x86_64
```

不能混用：

```text
arm64 Python + x86_64 target_arch
```

PyInstaller 只会替换 bootloader，  
不会把已经装好的 arm64 扩展模块变成 x86_64。

## 4. 没有 Intel Mac 时的构建方式

### 4.1 Rosetta 环境

在 Apple Silicon 上安装 Rosetta：

```bash
softwareupdate --install-rosetta
```

安装 x86_64 Homebrew 到 `/usr/local`，  
与 arm64 的 `/opt/homebrew` 分开。

然后使用 x86_64 Python：

```bash
arch -x86_64 /usr/local/bin/python3 -m venv .venv-x86
.venv-x86/bin/pip install -e .
```

检查：

```bash
file .venv-x86/bin/python
# Mach-O 64-bit executable x86_64
```

### 4.2 真实 Intel Mac

在 Intel Mac 上直接创建 x86_64 venv，  
这是最可靠的验证方式。

### 4.3 CI / 云 Mac

可使用 Intel CI 或云 Mac 构建。  
Apple Silicon 上的 Rosetta 构建只能做冒烟测试，  
不能替代真实 Intel 机器。

## 5. 外部工具

### soundstretch

需要：

```text
x86_64 soundstretch
x86_64 libSoundTouch.1.dylib
```

不能直接复制：

```text
/opt/homebrew/bin/soundstretch
```

构建时显式指定：

```bash
MOMO_SOUNDSTRETCH=/usr/local/bin/soundstretch
MOMO_SOUNDTOUCH_LIB=/usr/local/lib/libSoundTouch.1.dylib
```

### ffmpeg

full 包需要 x86_64 ffmpeg：

```bash
MOMO_FFMPEG=/usr/local/bin/ffmpeg
```

thin 包不内置 ffmpeg，  
由用户自行安装 Intel ffmpeg。

## 6. 需要修改的构建文件

### 6.1 `packaging/momo_uta.spec`

当前：

```python
target_arch="arm64"
```

改成从环境变量读取：

```python
TARGET_ARCH = os.environ.get("MOMO_TARGET_ARCH", "arm64")
...
target_arch=TARGET_ARCH
```

### 6.2 `packaging/build.sh`

当前 thin / full 产物同名，  
Intel 构建会覆盖 arm64 包。

需要增加：

```text
MOMO_TARGET_ARCH=arm64|x86_64
按架构分 dist 目录
zip 文件名带架构
VERSIONS.txt 记录架构
```

示例目标布局：

```text
dist/arm64/thin/momo-uta-thin.app
dist/x86_64/thin/momo-uta-thin.app
dist/momo-uta-thin-arm64.zip
dist/momo-uta-thin-x86_64.zip
```

### 6.3 工具查找

`_find_tool()` 目前优先找：

```text
/opt/homebrew/bin
```

需要按目标架构筛选：

```text
MOMO_TARGET_ARCH=x86_64
→ 只接受 x86_64 工具
→ /usr/local/bin 优先
```

最稳妥的方式仍然是显式传：

```text
MOMO_FFMPEG
MOMO_SOUNDSTRETCH
MOMO_SOUNDTOUCH_LIB
```

### 6.4 签名

每个架构单独签名：

```text
arm64 app   → Developer ID
x86_64 app  → Developer ID
```

不在第一版做 universal2。

## 7. universal2 的问题

universal2 需要一个 `.app` 同时包含：

```text
arm64 + x86_64
```

这要求所有依赖都是 universal2：

```text
Python
pyobjc
sudachipy
numpy
soundstretch
libSoundTouch
ffmpeg
torch（full）
```

成本高，  
且 torch 是否提供 universal2 需要单独确认。

第一版建议：

```text
arm64 独立包
x86_64 独立包
```

不做 universal2。

## 8. 构建命令草案

在 x86_64 环境中：

```bash
arch -x86_64 /usr/local/bin/python3 -m venv .venv-x86
.venv-x86/bin/pip install -e .

MOMO_TARGET_ARCH=x86_64 \
MOMO_SOUNDSTRETCH=/usr/local/bin/soundstretch \
MOMO_SOUNDTOUCH_LIB=/usr/local/lib/libSoundTouch.1.dylib \
MOMO_FFMPEG=/usr/local/bin/ffmpeg \
./packaging/build.sh thin
```

当前 `build.sh` 还不支持 `MOMO_TARGET_ARCH`，  
需要先完成第 6 节的修改。

## 9. 验证清单

### 架构

```bash
file dist/x86_64/thin/momo-uta-thin.app/Contents/MacOS/momo-uta-thin
lipo -archs dist/x86_64/thin/momo-uta-thin.app/Contents/MacOS/momo-uta-thin
```

必须看到：

```text
x86_64
```

### 依赖

```bash
file .venv-x86/lib/python3.13/site-packages/sudachipy/_sudachipy*.so
file dist/x86_64/thin/momo-uta-thin.app/Contents/Frameworks/bin/soundstretch
```

### 运行

在 Apple Silicon 上通过 Rosetta 启动 x86 包，检查：

```text
能启动
能播放
能变速
能升降 key
能编辑 LRC
能保存歌词
```

### 真实 Intel

至少在以下场景验证：

```text
macOS 12
macOS 13/14（如可用）
无 arm64 Homebrew
干净 PATH
```

Rosetta 冒烟测试不能替代真实 Intel 验证。

## 10. 已知限制

```text
Rosetta 下性能不代表真实 Intel
老 Intel CPU 的 full 人声分离会很慢
PyTorch Intel wheel 供应情况需要单独确认
没有真实 Intel 机器时不能宣称“已验证”
```

## 11. 推荐发布策略

```text
Apple Silicon
  arm64 thin
  arm64 full

Intel
  先只发 x86_64 thin
  full 等 torch / 真机验证后再决定
```

README 和下载页需要明确标注：

```text
Intel：thin / x86_64 / macOS 12+
Apple Silicon：thin + full / arm64
```
