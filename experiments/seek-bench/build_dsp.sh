#!/bin/sh
set -eu
cd "$(dirname "$0")"
S=$(brew --prefix sound-touch)
R=$(brew --prefix rubberband)
clang++ -std=c++17 -O2 \
  -I"$S/include" -I"$R/include" \
  seek_dsp.cpp \
  -L"$S/lib" -L"$R/lib" \
  -lSoundTouch -lrubberband \
  -o seek_dsp
