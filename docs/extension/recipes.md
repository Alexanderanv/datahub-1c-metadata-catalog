# Recipes

Примеры recipe находятся в:

```text
examples/recipes/
```

Основные файлы:

- `1c-minimal.dhub.yaml`: только логический слой 1С.
- `1c-full.dhub.yaml`: логический слой 1С, кастомные аспекты, lineage и DB
  mapping.
- `db-postgres.dhub.yaml`: опциональный проход по физической базе PostgreSQL.

## Основные секции

`infobase` идентифицирует информационную базу 1С:

```yaml
infobase:
  name: ${ONEC_INFOBASE_NAME}
  display_name: ${ONEC_INFOBASE_DISPLAY_NAME:-${ONEC_INFOBASE_NAME}}
```

`object_filters` выбирает объекты метаданных:

```yaml
object_filters:
  include_objects:
    Documents:
      - ЗаказПокупателя
    Catalogs: []
  common_filters:
    tabular_sections:
      - ДополнительныеРеквизиты
```

Пустой список для типа означает "все объекты этого типа". Для больших
конфигураций лучше указывать явные списки объектов.

`ingestion` управляет тем, какие данные создаёт коннектор:

```yaml
ingestion:
  attributes: true
  tabular_sections: true
  lineage: true
  db_mapping: true
  emit_db_siblings: true
  emit_custom_aspects: true
```

`integration_services` выбирает HTTP/Web-сервисы. Они представляются как
процессы DataHub (`DataFlow`/`DataJob`) и не создают внешние outputs со
стороны source-коннектора 1С.

## Удаление объектов, пропавших из набора загрузки

По умолчанию повторная загрузка обновляет найденные сущности, но не удаляет из
DataHub объекты, которые пропали из `object_filters` или из ответа API 1С.
Чтобы включить контролируемое удаление, добавьте `pipeline_name` и
`stateful_ingestion`:

```yaml
pipeline_name: onec-1c-test-dev

source:
  type: 1c-enterprise
  config:
    stateful_ingestion:
      enabled: true
      remove_stale_metadata: true
      fail_safe_threshold: 75.0
      state_provider:
        type: datahub
        config:
          server: ${DATAHUB_GMS_URL}
          token: ${DATAHUB_GMS_TOKEN:-}
```

Механизм хранит список 1С-сущностей прошлого успешного запуска в DataHub и на
следующем запуске выставляет `removed=true` только тем сущностям, которые
раньше принадлежали этому же source, но теперь отсутствуют в текущем наборе
загрузки.
Под управление попадают 1С datasets, контейнеры информационной базы/видов
объектов и процессы 1С (`DataFlow`/`DataJob`). Физические DB-таблицы,
ручные связи в UI и внешние связи lineage этим механизмом не удаляются.

Если DataHub GMS требует авторизацию, примеры recipe используют:

```yaml
sink:
  type: datahub-rest
  config:
    server: ${DATAHUB_GMS_URL}
    token: ${DATAHUB_GMS_TOKEN:-}
```
