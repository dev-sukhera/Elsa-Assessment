PY ?= .venv/bin/python
PACKAGE := dist/realtime-quiz-submission.zip

.PHONY: install test mutation run run-redis load-test clean package

install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

test:
	$(PY) -m pytest -q --timeout 30

mutation:
	$(PY) scripts/mutation_check.py

run:
	$(PY) -m uvicorn quiz_server.app:create_app --factory --port 8000

run-redis:
	QUIZ_STORE=redis $(PY) -m uvicorn quiz_server.app:create_app --factory --port 8000

load-test:
	$(PY) scripts/load_test.py --quizzes 20 --players 50

clean:
	find . -path ./.venv -prune -o -name __pycache__ -type d -exec rm -rf {} +
	rm -rf .pytest_cache dist

# Submission zip: source, tests, docs and deployment files only.
package: clean
	mkdir -p dist
	zip -rq $(PACKAGE) . \
		-x '.venv/*' '.git/*' 'dist/*' '*__pycache__*' '.pytest_cache/*' \
		   'VIDEO_SCRIPT.md' '.DS_Store' '*/.DS_Store'
	@echo "wrote $(PACKAGE)"
	@unzip -l $(PACKAGE) | tail -1
