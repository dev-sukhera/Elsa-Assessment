PY ?= .venv/bin/python
HOST ?= 127.0.0.1
PACKAGE := dist/realtime-quiz-submission.zip

.PHONY: install lint test mutation run run-redis load-test clean package

install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

lint:
	$(PY) -m ruff check .

test:
	$(PY) -m pytest -q --timeout 30

mutation:
	$(PY) scripts/mutation_check.py

ENV_FILE := $(if $(wildcard .env),--env-file .env)

run:
	$(PY) -m uvicorn quiz_server.app:create_app --factory --host $(HOST) --port 8000 $(ENV_FILE)

run-redis:
	QUIZ_STORE=redis $(PY) -m uvicorn quiz_server.app:create_app --factory --host $(HOST) --port 8000 $(ENV_FILE)

load-test:
	$(PY) scripts/load_test.py --quizzes 20 --players 50

clean:
	find . -path ./.venv -prune -o -name __pycache__ -type d -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache dist

# Submission zip: source, tests, docs and deployment files only.
package: clean
	mkdir -p dist
	zip -rq $(PACKAGE) . \
		-x '.venv/*' 'project_venv/*' '.git/*' 'dist/*' '*__pycache__*' '.pytest_cache/*' '.ruff_cache/*' \
		   '.env' 'VIDEO_SCRIPT.md' '.DS_Store' '*/.DS_Store'
	@echo "wrote $(PACKAGE)"
	@unzip -l $(PACKAGE) | tail -1
