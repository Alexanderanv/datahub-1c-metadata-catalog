# Быстрый демонстрационный запуск

Этот сценарий нужен, чтобы быстро посмотреть расширение DataHub для 1С в
локальном DataHub quickstart. Это демонстрационный режим, а не рекомендуемая
производственная архитектура.

В production окружении владелец DataHub самостоятельно решает вопросы TLS,
SSO, резервного копирования, мониторинга, ресурсов, хранения секретов,
отказоустойчивости и обновлений.

## Что делает demo-режим

Demo-режим помогает:

- установить зависимости коннектора и MFE;
- поднять локальный DataHub quickstart через DataHub CLI;
- собрать и подключить кастомную метамодель 1С;
- выполнить reference ingest по recipe из `examples/recipes`;
- опционально запустить MFE server для 1C Metadata Explorer.

Demo-режим не выполняет:

- настройку production DataHub;
- настройку TLS, SSO и прав доступа;
- автоматический деплой расширения 1С в информационную базу;
- автоматическую выдачу лицензии 1С для `ConfigDumpInfo` exporter.

## Предварительные условия

На машине должны быть установлены:

- Docker;
- Python 3.11;
- JDK и Gradle либо доступ к Docker Hub для автоматической сборки через
  контейнер `gradle:8.9-jdk17`;
- Node.js и npm;
- доступный сервис метаданных 1С;
- выгруженный `ConfigDumpInfo.xml` для той же конфигурации 1С.

Если включена загрузка физической базы данных, также нужен доступ к этой базе.

## Подготовка окружения

Скопируйте пример переменных окружения:

```bash
cp datahub/.env.example .env
```

Заполните как минимум:

```env
ONEC_BASE_URL=http://<host>/<publication>/hs/metadataservice
ONEC_USERNAME=<user>
ONEC_PASSWORD=<password>
ONEC_CONFIG_DUMP_INFO_PATH=/path/to/ConfigDumpInfo.xml
ONEC_INFOBASE_NAME=1c-test
ONEC_INFOBASE_DISPLAY_NAME=1c-test
DATAHUB_GMS_URL=http://localhost:8080
```

Если нужна загрузка физической базы:

```env
POSTGRES_INGEST_ENABLED=true
POSTGRES_HOST_PORT=<host>:5432
POSTGRES_DATABASE=1c-test
POSTGRES_SCHEMA=public
POSTGRES_USERNAME=<user>
POSTGRES_PASSWORD=<password>
```

Если физическую базу пока загружать не нужно:

```env
POSTGRES_INGEST_ENABLED=false
```

## Подготовка recipe

`make demo.ingest` может работать с готовыми примерами recipe, но перед
пилотной загрузкой обычно стоит сделать свой recipe на основе
`examples/recipes/1c-full.dhub.yaml`.

В примере `1c-full.dhub.yaml` пустые списки в
`object_filters.include_objects` означают "все объекты этого типа":

```yaml
object_filters:
  include_objects:
    Catalogs: []
    Documents: []
    InformationRegisters: []
```

Пустые списки в `integration_services.include_services` работают так же для
HTTP/Web-сервисов.

Для большой конфигурации 1С это может быть долго и избыточно. Для первой
проверки сузьте список до нескольких нужных объектов:

```yaml
object_filters:
  include_objects:
    Catalogs:
      - Номенклатура
      - Контрагенты
    Documents:
      - ЗаказПокупателя
```

Подключите свой recipe через `.env`:

```env
ONEC_RECIPE=/path/to/1c-demo.dhub.yaml
```

## Установка зависимостей

```bash
make install
```

Эта команда создаёт `datahub/.venv`, устанавливает DataHub source-коннектор и
зависимости MFE.

Если подходящий Python не найден автоматически, укажите путь явно:

```bash
make install PYTHON=/path/to/python3.11
```

## Запуск DataHub quickstart

```bash
make demo.up
```

По умолчанию используется версия:

```text
DATAHUB_QUICKSTART_VERSION=v1.5.0.2
```

Версию можно изменить через `.env` или переменную окружения.

## Подключение кастомной метамодели

Если в recipe включено `emit_custom_aspects: true`, перед загрузкой нужно
собрать кастомную метамодель и перезапустить GMS:

```bash
make demo.prepare
```

Команда выполняет:

1. запуск DataHub quickstart;
2. сборку `custom-models` локальным Gradle или через Docker fallback;
3. распаковку model plugin в `~/.datahub/plugins/models`;
4. перезапуск контейнера GMS;
5. проверку, что GMS видит модель `custom-onec`.

Makefile пытается определить имя GMS-контейнера автоматически. Если это не
сработало, задайте имя явно:

```bash
DATAHUB_GMS_CONTAINER=<container-name> make demo.prepare
```

## Загрузка метаданных

```bash
make demo.ingest
```

Команда запускает `datahub/scripts/reference_ingest.py`.

По умолчанию используются:

- `examples/recipes/1c-full.dhub.yaml` для метаданных 1С;
- `examples/recipes/db-postgres.dhub.yaml` для физической базы данных.

Если в `.env` задан `ONEC_RECIPE`, runner использует этот recipe вместо
`examples/recipes/1c-full.dhub.yaml`. Если нужен нестандартный recipe для
физической базы, задайте `DB_RECIPE`.

Перед загрузкой runner проверяет `ConfigDumpInfo.xml`, проверяет наличие
кастомной метамодели при необходимости, затем выполняет загрузку 1С и
опционально загрузку физической базы.

## Опциональный запуск MFE

Сначала заполните `deploy/reference/.env`:

```bash
cp deploy/reference/.env.example deploy/reference/.env
```

Затем запустите MFE server:

```bash
make demo.mfe.up
```

Команда сначала собирает MFE bundle, затем запускает статический сервер из
`deploy/reference`.

Remote entry будет доступен по адресу:

```text
http://localhost:3002/remoteEntry.js
```

Если порт `3002` занят, измените `ONEC_MFE_PORT` в `deploy/reference/.env`
и повторите команду. Например:

```env
ONEC_MFE_PORT=3003
```

Чтобы DataHub frontend начал показывать MFE, его нужно настроить на загрузку
этого remote entry. Подробнее см. [MFE](mfe.md).

## Остановка demo-контура

```bash
make demo.down
make demo.mfe.down
```

`demo.down` останавливает DataHub quickstart через DataHub CLI.
`demo.mfe.down` останавливает только MFE server из `deploy/reference`.
