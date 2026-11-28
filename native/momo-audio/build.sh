#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
mkdir -p dist/native
swiftc -O native/momo-audio/main.swift -o dist/native/momo-audio
echo "built dist/native/momo-audio"
