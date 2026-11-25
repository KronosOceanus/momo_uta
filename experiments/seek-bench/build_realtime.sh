#!/bin/sh
set -eu
cd "$(dirname "$0")"
S=$(brew --prefix sound-touch)
R=$(brew --prefix rubberband)
clang++ -std=c++17 -O2 \
  -I"$S/include" -I"$R/include" \
  dsp_play.cpp \
  -L"$S/lib" -L"$R/lib" \
  -lSoundTouch -lrubberband \
  -framework AudioToolbox -framework AudioUnit -framework CoreAudio -framework CoreFoundation \
  -o dsp_play
clang++ -std=c++17 -O2 au_play.cpp \
  -framework AudioToolbox -framework AudioUnit -framework CoreAudio -framework CoreFoundation \
  -o au_play
