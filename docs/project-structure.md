# Структура проекта

Репозиторий оформлен как open source расширение DataHub для 1С:Предприятия.
Внутри есть несколько самостоятельных артефактов: сервис метаданных 1С,
source-коннектор DataHub, кастомная метамодель DataHub, опциональный MFE,
инструменты загрузки и демонстрационный контур.

## Верхний уровень

```text
datahub-1c-metadata-catalog/
├── README.md                         # точка входа в проект
├── Makefile                          # переносимые команды установки, сборки и demo-запуска
├── 1c-metadata-service/              # сервис метаданных 1С и связанные инструменты
├── datahub/                          # Python source-коннектор DataHub
├── custom-models/                    # кастомная метамодель DataHub
├── onec-metadata-explorer-mfe/        # опциональный Micro Frontend
├── deploy/reference/                 # демонстрационный контур запуска
├── docs/                             # документация проекта
└── examples/recipes/                 # переносимые примеры recipe для загрузки
```

## Пользовательская документация

```text
docs/
├── project-structure.md              # этот файл
├── extension/                        # документация по установке и запуску расширения
│   ├── README.md
│   ├── concepts.md
│   ├── install-datahub-extension.md
│   ├── quickstart-demo.md
│   ├── 1c-metadata-service.md
│   ├── configdumpinfo.md
│   ├── recipes.md
│   ├── ingestion.md
│   ├── reference-deployment.md
│   ├── mfe.md
│   ├── verification.md
│   ├── operations-requirements.md
│   └── troubleshooting.md
└── ...
```

Основная пользовательская документация находится в `docs/extension/`.

## Сервис метаданных 1С

```text
1c-metadata-service/
├── api-spec/
│   └── openapi.yaml                  # OpenAPI-контракт сервиса метаданных
├── metadataservice-1c-extension/     # EDT-проект расширения 1С
├── configdump-exporter/              # Docker-инструмент выгрузки ConfigDumpInfo.xml
└── manual-lineage.md                 # описание ручных правил lineage для 1С
```

`api-spec/openapi.yaml` - контракт между сервисом 1С и DataHub-коннектором.
EDT-проект `metadataservice-1c-extension` содержит реализацию HTTP-сервиса
`MetadataService`.

`configdump-exporter/` нужен для автоматизации выгрузки `ConfigDumpInfo.xml`.
Он зависит от дистрибутивов платформы 1С и лицензирования в целевом окружении.

## Source-коннектор DataHub

```text
datahub/
├── pyproject.toml                    # Python-пакет acryl-datahub-1c-source
├── README.md                         # документация по коннектору
├── .env.example                      # пример локальных переменных окружения
├── src/datahub_1c/
│   ├── source.py                     # entry point DataHub Source
│   ├── config.py                     # схема recipe
│   ├── api/
│   │   ├── client.py                 # HTTP-клиент сервиса 1С
│   │   └── models.py                 # DTO ответов сервиса 1С
│   └── mapping/
│       ├── browse_paths.py           # пути навигации DataHub
│       ├── containers.py             # контейнеры DataHub
│       ├── custom_aspects.py         # запись кастомных аспектов
│       ├── datasets.py               # datasets 1С и физической базы
│       ├── db_mapping.py             # связь 1С с физическими таблицами
│       ├── integration_services.py   # HTTP/Web-сервисы 1С
│       ├── kind_properties.py        # свойства разных видов объектов 1С
│       ├── lineage.py                # lineage документов, регистров и ручных правил
│       ├── metadata_uuid.py          # UUID из ConfigDumpInfo.xml
│       ├── platform.py               # платформа 1c-enterprise
│       ├── relationships.py          # доменные связи 1С
│       ├── schema_fields.py          # поля schemaMetadata
│       ├── standard_attributes.py    # стандартные реквизиты 1С
│       ├── tabular_parts.py          # табличные части
│       ├── translit.py               # транслитерация
│       └── urn.py                    # построение URN
├── scripts/
│   ├── reference_ingest.py           # переносимый runner загрузки
│   ├── validate_configdump.py        # проверка ConfigDumpInfo.xml
│   ├── check_custom_models.py        # проверка загрузки кастомной метамодели
│   └── pg_tables_pattern.py          # allow-list физических таблиц из /db-mapping
├── tests/
│   ├── unit/                         # unit-тесты
│   └── integration/                  # golden/integration проверки коннектора
└── ...
```

`datahub/scripts/reference_ingest.py` - основной переносимый сценарий запуска
загрузки: он проверяет `ConfigDumpInfo.xml`, проверяет кастомную метамодель,
запускает 1С recipe и, при необходимости, recipe физической базы.

## Кастомная метамодель DataHub

```text
custom-models/
├── README.md
├── build.gradle
├── settings.gradle
├── registry/
│   └── entity-registry.yml           # регистрация кастомных аспектов
└── src/main/pegasus/io/github/alexanderanv/datahub/onec/
    ├── OneCObjectProperties.pdl
    ├── OneCCatalogProperties.pdl
    ├── OneCDocumentProperties.pdl
    ├── OneCRegisterProperties.pdl
    ├── OneCDbMapping.pdl
    └── OneCDomainRelationships.pdl
```

Этот артефакт добавляет в DataHub типизированные свойства 1С, DB mapping и
доменные связи. После сборки получается zip-плагин модели, который нужно
установить в GMS, если включены кастомные аспекты.

Каталоги `custom-models/build/`, `custom-models/.gradle/` и generated Java
файлы являются результатами сборки.

## 1C Metadata Explorer MFE

```text
onec-metadata-explorer-mfe/
├── README.md
├── package.json
├── package-lock.json
├── webpack.config.js
├── mfe.config.example.yaml           # пример регистрации MFE в DataHub
├── public/
│   └── index.html
└── src/
    ├── App.tsx
    ├── App.css
    ├── graphql.ts
    ├── index.tsx
    ├── mount.tsx
    ├── standalone.tsx
    └── types.ts
```

MFE - опциональный интерфейс только для чтения. Он не участвует в загрузке
метаданных и может быть включён или отключён независимо от коннектора.

## Демонстрационный контур

```text
deploy/reference/
├── README.md
├── .env.example
├── compose.yaml                      # ingestion-runner
├── compose.configdump.yaml           # опциональный ConfigDumpInfo exporter
├── compose.mfe.yaml                  # опциональный статический сервер MFE
└── ingestion/
    └── Dockerfile                    # образ runner загрузки
```

Этот контур не поднимает полноценный DataHub. Он предполагает, что DataHub GMS,
сервис метаданных 1С и физическая база данных доступны как внешние сервисы.
Его задача - воспроизводимо проверить установку расширения и запуск загрузки.

## Переносимые recipe-примеры

```text
examples/recipes/
├── README.md
├── 1c-minimal.dhub.yaml              # только логический слой 1С
├── 1c-full.dhub.yaml                 # полный пример 1С + custom aspects + lineage
└── db-postgres.dhub.yaml             # опциональный проход по PostgreSQL
```

Эти recipe не привязаны к локальному тестовому набору объектов и подходят как
стартовая точка для новых установок.

## Артефакты и ответственность

| Артефакт | Каталог | Основной инструмент | Результат |
|---|---|---|---|
| Сервис метаданных 1С | `1c-metadata-service/` | 1C EDT, OpenAPI | расширение 1С + `openapi.yaml` |
| Source-коннектор DataHub | `datahub/` | Python 3.11 | пакет `acryl-datahub-1c-source` |
| Кастомная метамодель DataHub | `custom-models/` | Gradle, PDL | model plugin zip для GMS |
| 1C Metadata Explorer MFE | `onec-metadata-explorer-mfe/` | npm, Webpack | static bundle / `remoteEntry.js` |
| Демонстрационный контур | `deploy/reference/` | Docker Compose | runner загрузки и опциональные сервисы |

## Что не является исходным кодом

Следующие каталоги обычно являются локальными результатами сборки или
кэшами и не должны использоваться как источник истины:

- `datahub/.venv/`, `datahub/.pytest_cache/`, `datahub/.mypy_cache/`,
  `datahub/.ruff_cache/`;
- `custom-models/build/`, `custom-models/.gradle/`;
- `onec-metadata-explorer-mfe/node_modules/`,
  `onec-metadata-explorer-mfe/dist/`,
  `onec-metadata-explorer-mfe/.npm-cache/`;
- локальные `.env` файлы и каталоги `deploy/reference/configdump*`.

## Минимальное окружение разработки

- Python 3.11 для `datahub/`.
- JDK и Gradle для `custom-models/`.
- Node.js и npm для `onec-metadata-explorer-mfe/`.
- Docker Compose для `deploy/reference/` и локальных проверок DataHub.
- EDT для изменения и проверки расширения 1С.
