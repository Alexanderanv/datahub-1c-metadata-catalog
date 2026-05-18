# Build and run helper for the 1C ConfigDumpInfo.xml exporter.

ONEC_VERSION ?= 8.3.27.1644
BASE_IMAGE ?= debian:12-slim
IMAGE ?= ghcr.io/alexanderanv/onec-configdump-exporter:$(ONEC_VERSION)
PLATFORM ?=
PLATFORMS ?= linux/amd64,linux/arm64
BUILDX_OUTPUT ?= type=oci,dest=$(CURDIR)/build/onec-configdump-exporter-$(ONEC_VERSION).oci.tar
OUTPUT_DIR ?= $(CURDIR)/out
WORK_DIR ?= $(CURDIR)/work
ENV_FILE ?= .env
DOCKER_BUILD_ARGS ?=
DOCKER_RUN_ARGS ?=

DOCKER_PLATFORM_ARG := $(if $(PLATFORM),--platform "$(PLATFORM)",)

.DEFAULT_GOAL := help

.PHONY: help build buildx run shell test clean dist.check

help:
	@echo "Targets:"
	@echo "  make build       — build local image for current Docker platform"
	@echo "  make buildx      — build multi-platform image ($(PLATFORMS)); writes $(BUILDX_OUTPUT)"
	@echo "  make run         — run one-shot export to $(OUTPUT_DIR)/ConfigDumpInfo.xml"
	@echo "  make shell       — open shell in exporter image"
	@echo "  make test        — run local smoke-test with fake 1cv8"
	@echo "  make dist.check  — show expected dist/ layout"
	@echo "Variables:"
	@echo "  ONEC_VERSION=$(ONEC_VERSION)"
	@echo "  IMAGE=$(IMAGE)"
	@echo "  BASE_IMAGE=$(BASE_IMAGE)"
	@echo "  PLATFORM=$(PLATFORM)"
	@echo "  PLATFORMS=$(PLATFORMS)"
	@echo "  BUILDX_OUTPUT=$(BUILDX_OUTPUT)"
	@echo "  ENV_FILE=$(ENV_FILE)"
	@echo "  DOCKER_BUILD_ARGS=$(DOCKER_BUILD_ARGS)"
	@echo "  DOCKER_RUN_ARGS=$(DOCKER_RUN_ARGS)"

dist.check:
	@echo "Expected layout:"
	@echo "  dist/$(ONEC_VERSION)/amd64/*.deb   or dist/$(ONEC_VERSION)/amd64/*.tar.gz"
	@echo "  dist/$(ONEC_VERSION)/arm64/*.deb   or dist/$(ONEC_VERSION)/arm64/*.tar.gz"
	@echo "Aliases x86_64 and arm64 are also accepted."
	@find dist -maxdepth 3 -type f | sort || true

build:
	docker build \
		$(DOCKER_PLATFORM_ARG) \
		--build-arg ONEC_VERSION="$(ONEC_VERSION)" \
		--build-arg BASE_IMAGE="$(BASE_IMAGE)" \
		--build-arg ONEC_UID="$$(id -u)" \
		--build-arg ONEC_GID="$$(id -g)" \
		$(DOCKER_BUILD_ARGS) \
		-t "$(IMAGE)" .

buildx:
	mkdir -p "$(CURDIR)/build"
	docker buildx build \
		--platform "$(PLATFORMS)" \
		--build-arg ONEC_VERSION="$(ONEC_VERSION)" \
		--build-arg BASE_IMAGE="$(BASE_IMAGE)" \
		--build-arg ONEC_UID="$$(id -u)" \
		--build-arg ONEC_GID="$$(id -g)" \
		$(DOCKER_BUILD_ARGS) \
		--output "$(BUILDX_OUTPUT)" \
		-t "$(IMAGE)" .

run:
	mkdir -p "$(OUTPUT_DIR)" "$(WORK_DIR)"
	test -f "$(ENV_FILE)"
	docker run --rm \
		$(DOCKER_PLATFORM_ARG) \
		$(DOCKER_RUN_ARGS) \
		--env-file "$(ENV_FILE)" \
		-v "$(OUTPUT_DIR):/out" \
		-v "$(WORK_DIR):/work" \
		"$(IMAGE)"

shell:
	test -f "$(ENV_FILE)"
	docker run --rm -it \
		$(DOCKER_PLATFORM_ARG) \
		$(DOCKER_RUN_ARGS) \
		--env-file "$(ENV_FILE)" \
		-v "$(OUTPUT_DIR):/out" \
		-v "$(WORK_DIR):/work" \
		--entrypoint bash \
		"$(IMAGE)"

test:
	tests/smoke_export_configdump.sh

clean:
	rm -rf "$(OUTPUT_DIR)"/* "$(WORK_DIR)"/*
