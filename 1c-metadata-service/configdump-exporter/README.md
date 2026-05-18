# 1C ConfigDumpInfo.xml Exporter

Этот подпроект готовит Docker-контейнер, который запускает `1cv8 DESIGNER` в
batch/headless-режиме и выгружает только `ConfigDumpInfo.xml` командой:

```bash
1cv8 DESIGNER ... /DumpConfigToFiles <dir> -Format Hierarchical -configDumpInfoOnly
```

Файл нужен DataHub-коннектору как authoritative источник стабильных UUID
метаданных 1С. Дистрибутивы платформы 1С не коммитятся в репозиторий.

Собранный image содержит установленные бинарные файлы платформы 1С. Его нельзя
публиковать в публичный registry; для `buildx`/CI используй только trusted
private builder и private registry/artifact storage. Raw `.deb`/`.tar.gz`
пакеты монтируются в Dockerfile через BuildKit bind mount и не копируются в
слои итогового образа, но build context всё равно должен обрабатываться как
licensed artifact.

## Что нужно скачать

Скачай с портала 1С Linux DEB-дистрибутивы той версии платформы, которая
совместима с целевой информационной базой. Нужен полный набор пакетов,
достаточный для установки толстого клиента/Designer (`1cv8`) через `apt`.
Для 8.3.27 DEB-пакет `client` зависит от `server`, а `server` — от `common`,
поэтому только `client`/`thin-client` недостаточно. Канонический набор для
exporter-а:

- `common`
- `common-nls`
- `server`
- `server-nls`
- `client`
- `client-nls`
- `thin-client` / `thin-client-nls` можно хранить рядом с остальными
  пакетами, но exporter намеренно пропускает их при установке: для
  `DumpConfigToFiles` нужен толстый клиент/Designer, а `thin-client`
  конфликтует с `common`/`server` в DEB-наборе 8.3.27
- `ws`/`crs` пакеты допускаются в `dist/`; текущий Dockerfile устанавливает все
  non-thin пакеты из набора, чтобы не ломать vendor dependency graph разных
  поставок 1С

Для разных версий и архитектур клади файлы так:

```text
dist/
  8.3.27.1644/
    amd64/
      *.deb
      # или архив deb64_*.tar.gz
    arm64/
      *.deb
      # или архив arm64_*.tar.gz
```

Для x86_64 можно использовать каталог `amd64` или `x86_64`.

На Apple Silicon самый надежный вариант для разработки — собрать/запустить
`linux/amd64` образ через Docker Desktop emulation, если под нужную версию 1С
нет подходящего Linux ARM64 client/designer-дистрибутива. Нативный
`linux/arm64` build поддержан Dockerfile-ом, но требует arm64-пакеты 1С.

## Настройка подключения

```bash
cp env.example .env
```

Серверная база:

```dotenv
ONEC_SERVER=1c-host
ONEC_INFOBASE=1c-test
ONEC_USERNAME=Администратор
ONEC_PASSWORD=
```

`ONEC_INFOBASE` должен быть reference name информационной базы на сервере 1С
для подключения Конфигуратора через `/S`, а не обязательно HTTP publication
path из URL вида `http://host/<publication>/hs/...`. Если они отличаются,
используй полный `ONEC_IB_CONNECTION`.

Файловая база:

```dotenv
ONEC_FILE_DB=/work/ib
ONEC_USERNAME=Администратор
ONEC_PASSWORD=
```

Или полный connection string:

```dotenv
ONEC_IB_CONNECTION=Srvr="1c-host";Ref="1c-test";
```

## Сборка и запуск

```bash
DOCKER_BUILDKIT=1 make build ONEC_VERSION=8.3.27.1644
make run
```

Для сборки/запуска конкретной архитектуры укажи `PLATFORM`:

```bash
DOCKER_BUILDKIT=1 make build ONEC_VERSION=8.3.27.1644 PLATFORM=linux/amd64
make run IMAGE=ghcr.io/alexanderanv/onec-configdump-exporter:8.3.27.1644 PLATFORM=linux/amd64
```

`Makefile` не читает `.env` как make include, чтобы случайно не
интерпретировать секреты как make-переменные. Для запуска контейнера
используется `ENV_FILE` (по умолчанию `.env`):

```bash
make run ENV_FILE=.env
```

Результат появится в:

```text
out/ConfigDumpInfo.xml
out/configdump-export.log
```

После этого в `datahub/.env` можно указать:

```dotenv
ONEC_CONFIG_DUMP_INFO_PATH=../1c-metadata-service/configdump-exporter/out/ConfigDumpInfo.xml
```

Если `apt` не может удовлетворить зависимости `.deb`, сборка останавливается.
Это сделано намеренно: принудительная распаковка неполного набора пакетов может
создать образ, где `1cv8` присутствует, но `DESIGNER` падает на старте. Для
локальной диагностики можно временно добавить build arg
`ONEC_ALLOW_UNSATISFIED_DEB_DEPS=true`, но такой образ не считается рабочим:

```bash
make build DOCKER_BUILD_ARGS='--build-arg ONEC_ALLOW_UNSATISFIED_DEB_DEPS=true'
```

## Multi-platform build

```bash
docker buildx create --use --name onec-builder
make buildx ONEC_VERSION=8.3.27.1644 PLATFORMS=linux/amd64,linux/arm64
```

`buildx` соберет оба варианта только если в `dist/<version>/<arch>/` есть
пакеты для каждой архитектуры. По умолчанию результат пишется в OCI-архив
`build/onec-configdump-exporter-<version>.oci.tar`. Для публикации в registry
явно передай:

```bash
make buildx \
  IMAGE=registry.example.com/datahub-1c/onec-configdump-exporter:8.3.27.1644 \
  BUILDX_OUTPUT=type=registry
```

Если есть только `amd64`, собирай и запускай:

```bash
docker build --platform linux/amd64 \
  --build-arg ONEC_VERSION=8.3.27.1644 \
  -t ghcr.io/alexanderanv/onec-configdump-exporter:8.3.27.1644 .
```

## Локальная проверка без платформы 1С

```bash
make test
```

Тест подставляет fake `1cv8`, проверяет сборку CLI-аргументов для server/file/
connection-string режимов и то, что entrypoint атомарно переносит
`ConfigDumpInfo.xml` в output directory.

## Запуск по расписанию

Контейнер сделан как one-shot job: при старте он выгружает файл и завершает
работу. Для расписания лучше использовать внешний оркестратор:

- cron/systemd timer на dev-машине;
- GitHub/GitLab CI runner с доступом к 1С-серверу;
- Airflow/Kubernetes CronJob в production.

Важно: контейнеру нужен сетевой доступ к 1С-серверу, совместимая версия
платформы 1С и лицензия/сервер лицензирования, достаточные для запуска
Конфигуратора.

Для Linux-контейнера нужен пакет `iproute2`: платформа 1С при проверке
окружения вызывает `/sbin/ip`. Без него перед ошибкой лицензирования появляется
диагностический шум `/sbin/ip: not found`, который маскирует реальную причину.
