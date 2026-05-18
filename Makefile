# Public helper commands for the 1C DataHub extension.
#
# The targets here are intentionally limited to portable onboarding tasks:
# installing dependencies, running tests, building artifacts, and starting a
# local DataHub quickstart for demonstration. Production DataHub deployment is
# owned by the target environment.

-include .env

PYTHON ?= $(shell \
	for candidate in python3.11 python3; do \
		if command -v $$candidate >/dev/null 2>&1 && \
			$$candidate -c 'import sys; raise SystemExit(not (sys.version_info[:2] == (3, 11)))' >/dev/null 2>&1; then \
			echo $$candidate; \
			exit 0; \
		fi; \
	done; \
	if command -v pyenv >/dev/null 2>&1; then \
		pyenv versions --bare | awk '/^3\.11\./ { print ENVIRON["HOME"] "/.pyenv/versions/" $$1 "/bin/python"; exit }'; \
	fi)
DATAHUB_VENV ?= datahub/.venv
DATAHUB_PY := $(DATAHUB_VENV)/bin/python
DATAHUB_CLI := $(DATAHUB_VENV)/bin/datahub
DATAHUB_GMS_URL ?= http://localhost:8080
DATAHUB_QUICKSTART_VERSION ?= v1.5.0.2
DATAHUB_GMS_CONTAINER ?= $(shell docker ps --format '{{.Names}}' 2>/dev/null | grep -E 'datahub-gms' | head -n 1)
CUSTOM_MODELS_PLUGIN_ROOT ?= $(HOME)/.datahub/plugins/models
CUSTOM_MODELS_DOCKER_IMAGE ?= gradle:8.9-jdk17

.DEFAULT_GOAL := help

.PHONY: help check.python install install.datahub install.mfe test test.datahub test.mfe build build.custom-models build.mfe custom-models.install custom-models.status demo.up demo.down demo.prepare demo.ingest demo.mfe.up demo.mfe.down clean

help:
	@echo "Targets:"
	@echo "  install                install Python and MFE dependencies"
	@echo "  install.datahub        create datahub/.venv and install the 1C source connector"
	@echo "  install.mfe            install MFE dependencies with npm ci"
	@echo "  test                   run connector tests and MFE checks"
	@echo "  build                  build custom models and MFE bundle"
	@echo "  custom-models.install  install custom model plugin into CUSTOM_MODELS_PLUGIN_ROOT"
	@echo "  custom-models.status   check that DataHub GMS exposes custom-onec models"
	@echo "  demo.up                start local DataHub quickstart for demonstration"
	@echo "  demo.prepare           demo.up + install custom models + restart GMS + status check"
	@echo "  demo.ingest            run reference 1C + optional database ingestion"
	@echo "  demo.down              stop local DataHub quickstart"
	@echo "  demo.mfe.up            start optional MFE server from deploy/reference"
	@echo "  demo.mfe.down          stop optional MFE server"

install: install.datahub install.mfe

check.python:
	@test -n "$(PYTHON)" || (echo "ERROR: Python 3.11 was not found. Run 'make install PYTHON=/path/to/python3.11'."; exit 1)
	@"$(PYTHON)" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else "ERROR: Python 3.11 is required. Run make with PYTHON=/path/to/python3.11")'

install.datahub: check.python
	@test -d "$(DATAHUB_VENV)" || "$(PYTHON)" -m venv "$(DATAHUB_VENV)"
	"$(DATAHUB_PY)" -m pip install --upgrade pip
	"$(DATAHUB_PY)" -m pip install -e "./datahub[dev,postgres]"

install.mfe:
	npm ci --prefix onec-metadata-explorer-mfe

test: test.datahub test.mfe

test.datahub: install.datahub
	"$(DATAHUB_PY)" -m pytest datahub/tests

test.mfe: install.mfe
	npm --prefix onec-metadata-explorer-mfe run check

build: build.custom-models build.mfe

build.custom-models:
	cd custom-models && \
		if command -v gradle >/dev/null 2>&1; then \
			gradle clean build; \
		else \
			docker run --rm -v "$$(pwd)":/workspace -w /workspace "$(CUSTOM_MODELS_DOCKER_IMAGE)" gradle clean build; \
		fi

build.mfe: install.mfe
	npm --prefix onec-metadata-explorer-mfe run build

custom-models.install: build.custom-models
	mkdir -p "$(CUSTOM_MODELS_PLUGIN_ROOT)"
	unzip -o custom-models/build/dist/custom-models.zip -d "$(CUSTOM_MODELS_PLUGIN_ROOT)"

custom-models.status: install.datahub
	DATAHUB_GMS_TOKEN="$(DATAHUB_GMS_TOKEN)" "$(DATAHUB_PY)" datahub/scripts/check_custom_models.py --server "$(DATAHUB_GMS_URL)"

demo.up: install.datahub
	"$(DATAHUB_CLI)" docker quickstart --version "$(DATAHUB_QUICKSTART_VERSION)"

demo.down: install.datahub
	"$(DATAHUB_CLI)" docker quickstart --stop

demo.prepare: demo.up custom-models.install
	@test -n "$(DATAHUB_GMS_CONTAINER)" || (echo "ERROR: DataHub GMS container was not found. Set DATAHUB_GMS_CONTAINER=<container-name>."; exit 1)
	docker restart "$(DATAHUB_GMS_CONTAINER)"
	@echo "Waiting 30 seconds for GMS to restart..."
	sleep 30
	DATAHUB_GMS_TOKEN="$(DATAHUB_GMS_TOKEN)" "$(DATAHUB_PY)" datahub/scripts/check_custom_models.py --server "$(DATAHUB_GMS_URL)"

demo.ingest: install.datahub
	set -a; test ! -f .env || . ./.env; set +a; DATAHUB_COMMAND="$(DATAHUB_CLI)" DATAHUB_GMS_URL="$(DATAHUB_GMS_URL)" "$(DATAHUB_PY)" datahub/scripts/reference_ingest.py

demo.mfe.up: build.mfe
	docker compose --env-file deploy/reference/.env -f deploy/reference/compose.yaml -f deploy/reference/compose.mfe.yaml --profile mfe up -d onec-metadata-explorer-mfe

demo.mfe.down:
	docker compose --env-file deploy/reference/.env -f deploy/reference/compose.yaml -f deploy/reference/compose.mfe.yaml --profile mfe down

clean:
	rm -rf datahub/.pytest_cache datahub/.mypy_cache datahub/.ruff_cache
	rm -rf custom-models/build custom-models/.gradle
	rm -rf onec-metadata-explorer-mfe/dist onec-metadata-explorer-mfe/.npm-cache
