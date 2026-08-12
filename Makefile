SHELL := /bin/sh

PYTHON_VERSION ?= 3.11
PYTHON_BIN ?=
VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
IMAGE ?= intention-playground
PORT ?= 8501
# docker-run app entry: full lab (app.py) or lightweight V1 (app_reference.py)
DOCKER_APP ?= app.py

.DEFAULT_GOAL := help

.PHONY: help setup install train run run-lab test benchmark benchmark-select benchmark-select-fair docker-build docker-run docker-run-ref docker-test clean

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: install .env ## Create the environment and local configuration

install: $(VENV)/.installed ## Install pinned dependencies

$(VENV)/bin/python:
	@if [ -n "$(PYTHON_BIN)" ]; then \
		"$(PYTHON_BIN)" -m venv $(VENV); \
	elif command -v python$(PYTHON_VERSION) >/dev/null 2>&1; then \
		python$(PYTHON_VERSION) -m venv $(VENV); \
	elif command -v mise >/dev/null 2>&1; then \
		mise exec python@$(PYTHON_VERSION) -- python -m venv $(VENV); \
	else \
		printf '%s\n' "Python $(PYTHON_VERSION) is required. Install it or run make setup PYTHON_BIN=/path/to/python." >&2; \
		exit 1; \
	fi

$(VENV)/.installed: requirements.txt $(VENV)/bin/python
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@touch $@

.env: .env.example
	cp .env.example .env

train: install ## Train or refresh the sklearn artifact
	$(PYTHON) scripts/train_sklearn.py

# Shared env for Streamlit on macOS (avoids OpenMP / ObjC fork crashes).
STREAMLIT_ENV := \
	OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
	OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES KMP_DUPLICATE_LIB_OK=TRUE \
	TOKENIZERS_PARALLELISM=false PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
	INTENTION_DEBUG=1 PYTHONFAULTHANDLER=1

run: install ## Start V1 Reference UI (lightweight; preferred on macOS)
	@mkdir -p logs
	@echo "Starting V1 Reference at http://localhost:$(PORT) — open the URL manually."
	@echo "Crash-repro log: logs/crash-repro.log  |  faulthandler: logs/faulthandler.dump"
	@echo "After a segfault, send the last ~40 lines of logs/crash-repro.log (and faulthandler.dump if non-empty)."
	$(STREAMLIT_ENV) \
	$(VENV)/bin/streamlit run app_reference.py --server.port=$(PORT) --server.headless=true --server.fileWatcherType=none

run-lab: install ## Start full Comparison Lab + V1 Reference (may segfault on some macOS hosts)
	@mkdir -p logs
	@echo "Starting full playground at http://localhost:$(PORT) — open the URL manually."
	@echo "If this exits with Segmentation fault: 11, use 'make run' (V1 only) or 'make docker-run'."
	@echo "Crash-repro log: logs/crash-repro.log  |  faulthandler: logs/faulthandler.dump"
	$(STREAMLIT_ENV) \
	$(VENV)/bin/streamlit run app.py --server.port=$(PORT) --server.headless=true --server.fileWatcherType=none

test: install ## Run the deterministic test suite
	$(VENV)/bin/pytest -q

benchmark: install ## Run Fake (default) Intention V1 model benchmark harness
	$(PYTHON) -m reference_runtime.benchmark_cli --providers $(or $(PROVIDERS),fake) --output-dir benchmark_reports

benchmark-select: install ## Parallel multi-model selection on core suite → comparison + primary/fallback
	$(PYTHON) -m reference_runtime.benchmark_cli --candidates $(or $(CANDIDATES),default) --suite $(or $(SUITE),core) --parallel --include-fake --output-dir benchmark_reports

benchmark-select-fair: install ## Sequential multi-model run (workers=1) for reproducible selection
	$(PYTHON) -m reference_runtime.benchmark_cli --candidates $(or $(CANDIDATES),default) --suite $(or $(SUITE),core) --parallel --workers 1 --include-fake --output-dir benchmark_reports

docker-build: ## Build the application image
	docker build -t $(IMAGE) .

# Streamlit flags inside Linux container (same hardening as make run).
DOCKER_STREAMLIT_FLAGS := --server.address=0.0.0.0 --server.port=8501 --server.headless=true --server.fileWatcherType=none

docker-run: ## Run full lab in Docker on PORT (default: 8501); uses .env if present
	@mkdir -p logs && chmod a+rwx logs
	@echo "Docker $(DOCKER_APP) at http://localhost:$(PORT) — open the URL manually."
	@echo "If this exits with Error 139 (SIGSEGV), retry: make docker-run-ref"
	@echo "Crash-repro (host): logs/crash-repro.log"
	docker run --rm -p $(PORT):8501 \
		$(if $(wildcard .env),--env-file .env,) \
		-e INTENTION_DEBUG=1 -e PYTHONFAULTHANDLER=1 \
		-e INTENTION_DEBUG_LOG=/app/logs/crash-repro.log \
		-e INTENTION_DEBUG_FAULT=/app/logs/faulthandler.dump \
		-e STREAMLIT_SERVER_HEADLESS=true \
		-e STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
		-v "$(CURDIR)/logs:/app/logs" \
		$(IMAGE) \
		streamlit run $(DOCKER_APP) $(DOCKER_STREAMLIT_FLAGS)

docker-run-ref: ## Run V1 Reference only in Docker (lighter; preferred if docker-run segfaults)
	$(MAKE) docker-run DOCKER_APP=app_reference.py

docker-test: docker-build ## Run tests inside the Python 3.11 image
	docker run --rm -v "$(CURDIR):/workspace" -w /workspace $(IMAGE) pytest -q

clean: ## Remove local caches, virtualenv, and generated model artifacts
	rm -rf $(VENV) .pytest_cache __pycache__ core/__pycache__ routers/__pycache__ scripts/__pycache__ tests/__pycache__
	rm -f models/*.joblib
