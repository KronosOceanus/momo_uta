# Nihongo_Acc · 常用命令
PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: help test test-python arch arch-python config-check app \
        build-tables build-resource build-holdout build-prose build-lyrics \
        eval-dummy eval eval-real eval-kanji eval-gen eval-test eval-llm \
        ceiling stats tables-check build-stats audit gold-audit audit-patches \
        render clean-cache all serve api

help:
	@echo "make test            # 完整检查（需要支持 node --test 的 Node.js）"
	@echo "make test-python     # Python 架构检查与测试"
	@echo "make app             # 桌面应用（唯一入口）"
	@echo "make serve           # 标注测试页 http://127.0.0.1:8765"
	@echo "make api             # 命令行跑一次接口，验证可用"
	@echo ""
	@echo "make build-tables    # JMdict → data/tables/*.json"
	@echo "make build-resource  # Uta-Net 非评测歌 → data/corpus/resource.json"
	@echo "make gold-audit      # 抽检 gold 本身（人工判）"
	@echo "make build-prose     # 青空文庫 → eval/gold/gold.jsonl"
	@echo "make build-lyrics    # Uta-Net 动漫榜 → eval/gold/lyrics.jsonl"
	@echo "make build-holdout   # Uta-Net 新歌 → eval/gold/lyrics_test.jsonl"
	@echo ""
	@echo "make eval-real       # 开发集（含拉丁）"
	@echo "make eval-kanji      # 开发集（只看日文 span，默认规则）"
	@echo "make      # 接入全部不确定规则（R1,R3,R4）"
	@echo "make eval-gen        # 泛化集（27 首，跨榜单）"
	@echo "make eval-test       # 留出集"
	@echo "make eval-dummy      # 空标注器，验证管线"
	@echo "make ceiling         # 表覆盖率（表能解释多少 span，不是上限）"
	@echo "make stats           # 弃权原因分布"
	@echo "make audit           # 溢出抽检"
	@echo "make audit-patches   # 人工补丁赚亏"
	@echo ""
	@echo "make eval-llm        # 带 LLM 的评测（默认不参与门禁）"
	@echo "make render          # 重新生成 demo 页"

config-check:
	@$(PY) -m nihonco_yomi.config

serve:
	$(PY) -m nihonco_yomi.serve

app:
	@$(PY) -m nihonco_player_app

api:
	@$(PY) -c "import nihonco_yomi; print(nihonco_yomi.Annotator().annotate('今日は雨が降る')['romaji']['text'])"

test: arch test-python
	node --test tests/lrc_editor.test.cjs

test-python: arch-python
	$(PY) -m unittest discover -s tests

arch: arch-python
	$(PY) scripts/check_js.py

arch-python:
	$(PY) scripts/check_arch.py

build-tables:
	$(PY) -m tools.build.build_tables

build-resource:
	$(PY) -m tools.fetch.fetch_jpop --resource --songs 25

build-holdout:
	$(PY) -m tools.fetch.fetch_jpop --holdout

build-prose:
	$(PY) -m tools.build.build_gold --works 40

build-lyrics:
	$(PY) -m tools.fetch.fetch_jpop --top 30

eval-dummy:
	$(PY) -m tools.eval.evalkit run --dummy --lyrics

eval:
	$(PY) -m tools.eval.evalkit run --annotator "$(CMD)" --lyrics

eval-real:
	$(PY) -m tools.eval.evalkit run --annotator "$(PY) -m nihonco_yomi.annotate --stdio" --lyrics

eval-kanji:
	$(PY) -m tools.eval.evalkit run --annotator "$(PY) -m nihonco_yomi.annotate --stdio" --lyrics --exclude-latin

eval-gen:
	$(PY) -m tools.eval.evalkit run --gold eval/gold/lyrics_gen.jsonl --annotator "$(PY) -m nihonco_yomi.annotate --stdio" --exclude-latin

eval-test:
	$(PY) -m tools.eval.evalkit run --gold eval/gold/lyrics_test.jsonl --annotator "$(PY) -m nihonco_yomi.annotate --stdio"

eval-llm:
	$(PY) -m tools.eval.evalkit run --annotator "$(PY) -m nihonco_yomi.annotate --stdio --llm --llm-min-conf 0.95" --lyrics

ceiling:
	$(PY) -m tools.eval.evalkit ceiling

stats:
	$(PY) -m tools.eval.evalkit stats

tables-check:
	$(PY) -m nihonco_yomi.annotate --check-tables

build-stats:
	$(PY) -m tools.build.build_corpus_stats

audit:
	$(PY) -m tools.eval.evalkit audit

gold-audit:
	$(PY) -m tools.eval.evalkit gold-audit

audit-patches:
	$(PY) -m tools.eval.evalkit patches


render:
	$(PY) -m tools.eval.render --songs アイドル 怪物

clean-cache:
	rm -rf data/cache/lyrics data/cache/wave data/cache/vocals
	@echo "已清理：歌词缓存 / 波形 / 人声（data/cache/app.log 保留）"

all: test build-prose build-lyrics eval-dummy
