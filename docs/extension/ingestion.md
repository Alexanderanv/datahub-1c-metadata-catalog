# Запуск загрузки

Runner загрузки находится в:

```text
datahub/scripts/reference_ingest.py
```

Он выполняет следующие шаги:

1. Проверяет `ConfigDumpInfo.xml`.
2. Проверяет, что DataHub GMS загрузил кастомную метамодель, если включены
   кастомные аспекты.
3. Запускает recipe source-коннектора 1С.
4. При необходимости запускает recipe физической базы данных.

Список разрешённых таблиц базы данных строится из API 1С `/db-mapping`. Он не
берётся из поискового индекса DataHub, потому что индекс может обновляться с
задержкой относительно загрузки.

Если DataHub GMS требует авторизацию, укажите:

```text
DATAHUB_GMS_TOKEN=<token>
```

Примеры recipe передают этот token в DataHub REST sink. Проверка кастомной
метамодели использует тот же token для обращения к `/config`.

## Локальная команда

Если вы запускаете runner напрямую, сначала экспортируйте переменные из `.env`:

```bash
set -a
source .env
set +a
```

```bash
datahub/.venv/bin/python datahub/scripts/reference_ingest.py \
  --onec-recipe examples/recipes/1c-full.dhub.yaml \
  --db-recipe examples/recipes/db-postgres.dhub.yaml
```

Отключайте проход по физической базе только если она недоступна:

```bash
POSTGRES_INGEST_ENABLED=false \
datahub/.venv/bin/python datahub/scripts/reference_ingest.py \
  --onec-recipe examples/recipes/1c-full.dhub.yaml
```

Если проход по физической базе отключён, DB schemas в DataHub останутся
скелетами, созданными на основе API 1С `/db-mapping`.

## Повторные запуски и удаление сущностей

При обычном повторном запуске коннектор обновляет сущности текущего набора
загрузки.
Сущности, которые раньше были загружены, но затем пропали из recipe или API
1С, остаются в DataHub.

Для удаления таких сущностей включите `stateful_ingestion` в recipe. Тогда
коннектор хранит checkpoint прошлого успешного запуска и при следующем
успешном запуске помечает пропавшие 1С-сущности как удалённые
(`Status.removed=true`). Физические DB-таблицы этим механизмом не управляются:
их lifecycle остаётся за стандартным DB-ingest или отдельным процессом.
