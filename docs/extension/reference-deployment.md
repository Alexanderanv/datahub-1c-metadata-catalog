# Демонстрационный контур

Демонстрационный контур находится в:

```text
deploy/reference/
```

Для самого быстрого локального запуска с DataHub quickstart см.
[Быстрый демонстрационный запуск](quickstart-demo.md). Этот документ описывает
более явный compose-контур, где DataHub GMS считается внешней зависимостью.

Он содержит:

- Docker Compose для runner загрузки.
- Опциональный Compose overlay для статического сервера MFE.
- Опциональный Compose overlay для ConfigDumpInfo exporter.
- `.env.example` с нужными переменными.

Запуск:

```bash
cd deploy/reference
cp .env.example .env
# отредактируйте .env
docker compose --env-file .env -f compose.yaml build ingestion-runner
docker compose --env-file .env -f compose.yaml run --rm ingestion-runner
```

DataHub GMS считается внешней зависимостью. Для локальной проверки это может
быть тестовая установка DataHub, запущенная на хостовой машине.

Если включены кастомные аспекты, перед запуском runner загрузки в GMS должна
быть установлена кастомная метамодель. Выполните из корня репозитория:

```bash
make custom-models.install
```

Если локальный Gradle не установлен, Makefile соберёт модель через Docker
образ `gradle:8.9-jdk17`.

После распаковки перезапустите GMS способом, принятым в вашей установке
DataHub.

Если GMS требует авторизацию, укажите `DATAHUB_GMS_TOKEN` в
`deploy/reference/.env`.

Демонстрационный контур не выполняет прямые изменения поискового индекса
DataHub. Он использует только публичные API DataHub ingestion.
