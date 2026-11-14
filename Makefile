.PHONY: lint test validate

lint:
	uv run --frozen ruff check scripts tests
	uv run --frozen ruff format --check scripts tests
	uv run --frozen python -c 'import ast, pathlib; [ast.parse(p.read_text()) for d in ("scripts", "tests") for p in pathlib.Path(d).rglob("*.py")]'

test:
	uv run --frozen pytest

validate:
	uv run --frozen python -B scripts/validate.py service templates/service.contract.json
	uv run --frozen python -B scripts/validate.py catalog catalog/services.json
