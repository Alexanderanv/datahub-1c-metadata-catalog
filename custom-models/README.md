# custom-models — кастомная метамодель DataHub для 1С

Модуль содержит PDL-схемы доменных аспектов и типизированных отношений для
объектов 1С:Предприятие. Собирается Gradle-ом в model-plugin, который
подкладывается в GMS через `~/.datahub/plugins/models/` без пересборки самого
DataHub.

## Состав

```text
src/main/pegasus/io/github/alexanderanv/datahub/onec/
├── OneCObjectProperties.pdl          # общие доменные поля объекта 1С
├── OneCCatalogProperties.pdl         # справочник / ПВХ
├── OneCDocumentProperties.pdl        # документ
├── OneCRegisterProperties.pdl        # регистр сведений/накопления
├── OneCDbMapping.pdl                 # маппинг 1С → DB table (колоночный)
└── OneCDomainRelationships.pdl       # @Relationship-поля, все без isLineage
registry/
└── entity-registry.yml               # привязка аспектов к dataset/container
```

Принципы:

- префикс `oneC` во всех именах аспектов — для изоляции от стандартного
  namespace DataHub;
- видо-специфичные свойства разнесены по отдельным аспектам
  (`OneCCatalogProperties`, `OneCDocumentProperties`, `OneCRegisterProperties`)
  — source-плагин эмитирует только релевантный для данного объекта;
- все `@Relationship`-поля **без** флага `isLineage:true` — они нужны
  как типизированные навигационные рёбра, но не должны засорять стандартный
  Lineage-граф;
- 1С может быть развёрнута на разных СУБД, поэтому доменный контракт custom
  aspects использует DB-neutral имена (`dbTableName`, `dbColumnName`,
  `mapsToDbTable`) и не привязывает UI к PostgreSQL/MS SQL/Oracle;
- аспекты, которые должны быть видны в стандартном DataHub UI, объявлены с
  `@Aspect.autoRender=true` и `renderSpec`. Сейчас auto-render включён для
  двух вкладок, которые дают устойчивое generic-представление без отдельного
  frontend fork/MFE.

## UI auto-render

DataHub v1.5.0.2 умеет рендерить custom aspects из `renderSpec`:

| Aspect | Вкладка | Renderer |
| ------ | ------- | -------- |
| `oneCObjectProperties` | `Properties 1C` | `properties` |
| `oneCDbMapping` | `Column mapping 1C` | `tabular`, key `attributeColumns` |

`oneCDbMapping` эмитится только когда `attributeColumns` содержит хотя бы
одну строку: generic `tabular` renderer DataHub v1.5.0.2 строит набор колонок
по первой строке массива и не рассчитан на пустую таблицу.

Остальные доменные аспекты (`oneCCatalogProperties`, `oneCDocumentProperties`,
`oneCRegisterProperties`, `oneCDomainRelationships`) остаются в метамодели и
GraphQL, но не auto-render-ятся штатным UI: для них нужен более осмысленный MFE,
а generic JSON/key-value вкладки дают слишком шумное представление.

## Сборка

Из корня репозитория:

```bash
make build.custom-models
```

Эта команда использует локальный Gradle, а если он не установлен — Docker
образ `gradle:8.9-jdk17`.

Ручная сборка из каталога `custom-models`:

```bash
gradle build
# → build/dist/custom-models.zip
```

Zip сразу содержит структуру, которую ожидает loader DataHub:

```text
custom-onec/
└── 0.1.0/
    ├── entity-registry.yml
    └── libs/
        └── custom-models-0.1.0.jar
```

## Установка в DataHub

```bash
unzip -o build/dist/custom-models.zip -d ~/.datahub/plugins/models/
# затем перезапустите GMS способом, принятым в вашей установке DataHub
```

Проверка после рестарта GMS:

```bash
python ../datahub/scripts/check_custom_models.py --server "$DATAHUB_GMS_URL"
```

Команда должна увидеть `custom-onec` версии `0.1.0` в `/config.models`.
После этого ingestion source-плагина (`../datahub/`) может класть `oneC*`
аспекты с корректной типизацией.

## Зависимости окружения

- JDK 17
- Gradle 8+ или Docker для сборки через Gradle container.
- Версии DataHub — синхронно с `../datahub/pyproject.toml` (сейчас 1.5.0.2).
