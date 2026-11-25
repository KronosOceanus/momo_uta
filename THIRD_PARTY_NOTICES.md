# Third-Party Notices

momo uta 本身使用 MIT License。  
打包版包含以下第三方程序或库。

## SoundTouch / soundstretch

```text
版本：2.4.1
许可证：GNU Lesser General Public License v2.1
用途：变速保持原调
```

随包文件：

```text
bin/soundstretch
bin/libSoundTouch.1.dylib
licenses/SoundTouch-LGPL-2.1.txt
```

源代码：

```text
https://www.surina.net/soundtouch/
https://github.com/soundtouch/soundtouch
```

如果需要重新链接或替换该库，可以使用随包的动态库路径：

```text
Contents/Frameworks/bin/libSoundTouch.1.dylib
```

## FFmpeg（仅 full 包）

```text
版本：7.1
许可证：GNU General Public License v3
用途：音频解码 / 格式转换 / 人声分离辅助
```

`full` 包随带：

```text
bin/ffmpeg
licenses/ffmpeg-GPLv3.txt
```

源代码：

```text
https://ffmpeg.org/
```

`thin` 包不包含 ffmpeg；需要系统自行安装。

## 说明

这些组件以独立可执行文件或独立动态库形式随包分发。  
发布或再分发时应保留上述许可证和版权声明。
