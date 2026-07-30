# career-copilot Makefile —— 测试 + lint + eval 门禁入口
# 跨平台：Windows CMD / PowerShell / bash 均可用（eval 改用 CLI 参数，不依赖 VAR=val cmd 语法）
# 用法：
#   make test          跑全量 pytest
#   make lint          ruff 检查
#   make typecheck     mypy 类型检查
#   make eval          本地 best-effort：agnes + repeat=2 真 LLM 门禁（gate FAIL → 非零退出，看真实信号；agnes 抽风重跑一次）
#   make eval-skip     CI 推荐（advisory）：LLM 不可达 / 抽风时 --skip-on-error 跳过（exit 0，不红 CI）
#   make resume-eval   简历生成质量 Eval（Phase 3.2，离线确定性门禁）：结构自检 + 5 case 全 5 维评分
#   make ci            完整 CI 流程（lint + typecheck + test + eval-skip + resume-eval）
#   make clean         清理 __pycache__
# 采用姿态（2026-07-21）：硬 CI 阻断在 flaky agnes 下不可靠（G3 已定不做），故 CI 用 eval-skip advisory；
#                       本地用 eval 作 best-effort 信号；(a) repeat=3+≥2/3、(b) nvidia 门禁暂不采用。
# 简历 Eval 为离线确定性门禁（不依赖 LLM 网关），可放心纳入 CI 硬阻断。

PY ?= python

.PHONY: test lint typecheck eval eval-skip resume-eval ci clean

test:
	$(PY) -m pytest tests/ -q

lint:
	$(PY) -m ruff check scripts/ tests/ evals/

typecheck:
	$(PY) -m mypy scripts/llm_client.py scripts/provider_chain.py --ignore-missing-imports

eval:
	$(PY) evals/run_dynamic_eval.py --provider agnes --repeat 2
	$(PY) evals/run_resume_eval.py --reference

eval-skip:
	$(PY) evals/run_dynamic_eval.py --provider agnes --repeat 2 --skip-on-error

resume-eval:
	$(PY) evals/run_resume_eval.py --check
	$(PY) evals/run_resume_eval.py --reference

ci: lint typecheck test eval-skip resume-eval
	@echo "CI passed"

clean:
	$(PY) -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]"
