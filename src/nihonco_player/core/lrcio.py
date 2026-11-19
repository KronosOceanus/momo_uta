#!/usr/bin/env python3
"""兼容壳：格式在 lrc_doc，文件 IO 在 lrc_files。"""
from __future__ import annotations

from .lrc_doc import (GEN, NHLRC_MARK, NHLRC_VERSION, _hash8,  # noqa: F401
                      _parse_document, _seg_list, _split_nhlrc,
                      annotations_for, fmt, parse, render, render_body,
                      render_nhlrc)
from .lrc_files import (LY, backup_candidates, backup_path,  # noqa: F401
                        backup_status, exists, import_text, load,
                        lrc_path, nhlrc_path, restore_backup, save)
