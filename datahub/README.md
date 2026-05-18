# datahub_1c — source-плагин DataHub для 1С:Предприятия

Плагин для DataHub, который выгружает метаданные конфигурации 1С:Предприятие
через REST-сервис `1c-metadata-service` (см. `../1c-metadata-service/api-spec/openapi.yaml`)
и эмитирует соответствующие сущности и аспекты в DataHub GMS.

## Назначение и область

- **Что плагин делает**: эмитирует `dataPlatformInfo` для платформы `1c-enterprise`,
  `Container` для объектов-владельцев табличных частей, `Dataset`-ы для объектов
  1С и их табличных частей, `SchemaMetadata` с полями и `ForeignKeyConstraint`,
  DB mapping к соответствующим физическим таблицам и опциональные `Siblings`,
  dataset-level lineage (`basis` и `manual_dataset_flow` напрямую,
  `register_movement` через process `DataFlow`/`DataJob`), доменные связи
  `RefersToObject` / `IsReferencedByObject`, а также кастомные аспекты `oneC*`
  (см. `../custom-models/`).
- **Что плагин НЕ делает**: не читает `1cv8.cf`-файлы напрямую; всё, что
  специфично для конкретной конфигурации, уходит в `1c-metadata-service`.
- **Поддерживаемая версия DataHub**: v1.5.0.x (acryl-datahub 1.5.0).

## Структура пакета

- `src/datahub_1c/api/` — HTTP-клиент и DTO ответов сервиса 1С.
- `src/datahub_1c/mapping/` — преобразование 1С DTO в аспекты DataHub.
- `src/datahub_1c/source.py` — orchestration DataHub Source.
- `scripts/` — переносимый runner загрузки, проверка `ConfigDumpInfo.xml`,
  проверка custom models и сбор allow-list физических DB-таблиц из `/db-mapping`.
- `tests/` — unit и integration/golden проверки emitted workunits.

## Локальная разработка

```bash
# из корня проекта
cd datahub
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# быстрые проверки
pytest
ruff check src tests scripts
mypy src scripts
```

## Запуск reference ingest

```bash
python scripts/reference_ingest.py \
  --onec-recipe ../examples/recipes/1c-full.dhub.yaml \
  --db-recipe ../examples/recipes/db-postgres.dhub.yaml
```

Он проверяет `ConfigDumpInfo.xml`, наличие кастомной метамодели в GMS, запускает
1С-ingest и при необходимости DB-ingest.

Allow-list таблиц для стандартного DB-ingest строится из authoritative
`/db-mapping` API 1С по текущему scope основного recipe. Если список таблиц не
удалось получить, команда падает fail-fast: DB-ingest является authoritative
источником реальной физической схемы и не должен молча превращаться в
«0 таблиц».
