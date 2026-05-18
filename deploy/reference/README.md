# Демонстрационный контур

Этот каталог содержит небольшой демонстрационный контур для проверки расширения
DataHub для 1С. Он предназначен для демонстраций и пилотных запусков. Это не
готовый промышленный дистрибутив DataHub.

Промышленные вопросы вроде TLS, SSO, резервного копирования, мониторинга,
подбора ресурсов Kafka/OpenSearch/SQL, хранения секретов, отказоустойчивости и
политики обновлений должен решать владелец установки DataHub.

## Компоненты

- `ingestion-runner`: устанавливает source-коннектор 1С и запускает pipeline
  загрузки.
- Опциональный `configdump-exporter`: выгружает `ConfigDumpInfo.xml` через 1C
  Designer, если в контейнере доступны платформа 1С и лицензия.
- Опциональный `onec-metadata-explorer-mfe`: отдаёт уже собранные статические
  файлы MFE. DataHub frontend всё равно нужно отдельно настроить на загрузку
  этого remote entry.

DataHub GMS считается внешней зависимостью. Для локальных проверок это может
быть тестовая установка DataHub, запущенная на хостовой машине.

## Предварительные условия

Перед запуском загрузки:

1. DataHub GMS должен быть запущен и доступен по `DATAHUB_GMS_URL`.
2. Если `ONEC_EMIT_CUSTOM_ASPECTS=true`, установите кастомную метамодель 1С в
   DataHub GMS и перезапустите GMS.
3. Сервис метаданных 1С должен быть доступен по `ONEC_BASE_URL`.
4. `ConfigDumpInfo.xml` должен быть выгружен из той же конфигурации 1С.
5. Если `POSTGRES_INGEST_ENABLED=true`, физическая база данных должна быть
   доступна.

Кастомную метамодель можно собрать и установить так:

```bash
cd custom-models
gradle build
unzip -o build/dist/custom-models.zip -d ~/.datahub/plugins/models/
```

После распаковки перезапустите GMS способом, принятым в вашей установке
DataHub. Ожидается такая структура:

```text
custom-onec/
└── 0.1.0/
```

Если целевой DataHub GMS требует авторизацию, укажите `DATAHUB_GMS_TOKEN` в
`.env`.

## Режим подготовленного ConfigDumpInfo

Основной и наиболее предсказуемый режим - заранее подготовленный файл:

1. Выгрузите `ConfigDumpInfo.xml` из Конфигуратора 1С или EDT.
2. Положите файл в `deploy/reference/configdump/ConfigDumpInfo.xml`.
3. Укажите `ONEC_CONFIG_DUMP_INFO_PATH=/configdump/ConfigDumpInfo.xml` в
   `.env`.

Runner загрузки проверяет файл перед загрузкой и может сравнить текущую область
recipe с ответами API 1С.

## Запуск

```bash
cd deploy/reference
cp .env.example .env
# отредактируйте .env
docker compose --env-file .env -f compose.yaml build ingestion-runner
docker compose --env-file .env -f compose.yaml run --rm ingestion-runner
```

Runner загрузки выполняет:

1. Проверку `ConfigDumpInfo.xml`.
2. Проверку кастомной метамодели в DataHub GMS, если включены кастомные
   аспекты.
3. Загрузку метаданных 1С.
4. Опциональную загрузку физической базы данных. Allow-list таблиц строится из
   API 1С `/db-mapping` для той же области recipe.

## Опциональный ConfigDumpInfo exporter

```bash
docker compose --env-file .env \
  -f compose.yaml \
  -f compose.configdump.yaml \
  --profile configdump \
  run --rm configdump-exporter
```

Этот режим зависит от рабочей установки платформы 1С и лицензии внутри
контейнера. Если лицензию нельзя использовать в headless/container режиме,
оставьте подготовленный файл основным способом работы.

Exporter использует параметры подключения 1C Designer, а не URL HTTP-сервиса
метаданных:

- `ONEC_SERVER` + `ONEC_INFOBASE` для серверной информационной базы;
- `ONEC_IB_CONNECTION` для полной строки подключения Designer;
- `ONEC_FILE_DB` для файловой информационной базы.

`ONEC_INFOBASE` - это Ref информационной базы сервера 1С, который использует
Designer. Он может отличаться от `ONEC_INFOBASE_NAME` - стабильного
пространства имён DataHub для URN и навигации.

## Опциональный MFE

```bash
docker compose --env-file .env \
  -f compose.yaml \
  -f compose.mfe.yaml \
  --profile mfe \
  up -d onec-metadata-explorer-mfe
```

Remote entry будет доступен по адресу:

```text
http://localhost:3002/remoteEntry.js
```

Зарегистрируйте этот URL в MFE-конфигурации DataHub frontend. Подробнее:
`docs/extension/mfe.md`.
