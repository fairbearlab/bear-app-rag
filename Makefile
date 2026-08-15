# Developer entry points. Each target mirrors a CI job in .github/workflows/ci.yml.
.PHONY: help sync lint format typecheck test eval eval-judge audit check hooks

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

sync: ## Install the project with all extras
	uv sync --all-extras

lint: ## ruff check + format check (read-only)
	uv run ruff check .
	uv run ruff format --check .

format: ## Apply ruff autofixes and formatting
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## mypy over bear_rag
	uv run mypy

test: ## Default pytest suite (eval-marked tests excluded)
	uv run pytest

eval: ## Deterministic eval benchmark
	uv run pytest -m eval -v

eval-judge: ## Eval with the LLM judge; key injected from 1Password via .env.example
	op run --env-file=.env.example -- env EVAL_LLM_JUDGE=1 uv run pytest -m eval -v

audit: ## pip-audit against the locked dependency set (same invocation as CI)
	uv export --all-extras --no-emit-project --no-hashes -o requirements-audit.txt
	uvx pip-audit --strict --no-deps --disable-pip -r requirements-audit.txt \
		--ignore-vuln PYSEC-2026-311
	rm -f requirements-audit.txt

check: lint typecheck test eval ## Everything CI runs, minus the audit

hooks: ## Install the pre-commit hooks
	uv run pre-commit install
