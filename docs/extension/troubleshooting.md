# Диагностика проблем

## Кастомные аспекты падают с unknown aspect

DataHub GMS не загрузил кастомную метамодель. Выполните:

```bash
python datahub/scripts/check_custom_models.py --server "$DATAHUB_GMS_URL"
```

Установите плагин модели или укажите `ONEC_EMIT_CUSTOM_ASPECTS=false` для
загрузки без кастомных аспектов.

## Проверка ConfigDumpInfo завершается ошибкой

Проверьте, что файл:

- существует по пути `ONEC_CONFIG_DUMP_INFO_PATH`;
- относится к той же конфигурации 1С, что и сервис метаданных;
- не устарел, если задан `CONFIGDUMP_MAX_AGE_SECONDS`;
- содержит UUID для всех объектов, выбранных в recipe.

Команда проверки:

```bash
python datahub/scripts/validate_configdump.py \
  --recipe examples/recipes/1c-full.dhub.yaml \
  --check-scope
```

## Загрузка падает с `UUID not found in ConfigDumpInfo.xml`

Это означает, что HTTP-сервис 1С вернул объект, табличную часть, HTTP/Web-сервис
или endpoint, для которого нет UUID в `ConfigDumpInfo.xml`. Коннектор
останавливает загрузку, потому что без UUID нельзя построить стабильный URN
DataHub.

Проверьте:

- `ConfigDumpInfo.xml` выгружен из той же основной конфигурации 1С, к которой
  подключён HTTP-сервис метаданных;
- после изменения конфигурации файл был выгружен заново;
- recipe не включает объект, который появился только в расширении или в другой
  версии конфигурации.

## Загрузка базы данных не загружает таблицы

Allow-list таблиц базы данных строится из `/db-mapping`. Проверьте:

- `ONEC_BASE_URL`, имя пользователя и пароль;
- выбранные объекты в `object_filters`;
- ответы `/db-mapping/{type}/{name}`;
- `POSTGRES_DATABASE` и `POSTGRES_SCHEMA`.

## Пропавший из recipe объект остался в DataHub

Это ожидаемое поведение, если `stateful_ingestion.enabled` не включён.
Обычный повторный ingest обновляет сущности, которые source снова увидел, но
не знает, какие старые сущности нужно считать удалёнными.

Для контролируемого удаления включите `stateful_ingestion` в recipe и задайте
стабильный `pipeline_name`. После второго успешного запуска DataHub получит
`Status.removed=true` для 1С-сущностей, которые были в предыдущем наборе
загрузки, но пропали из текущего.

Если удаление не сработало, проверьте:

- `pipeline_name` не менялся между запусками;
- `state_provider` указывает на тот же DataHub GMS;
- в отчёте source нет ошибок: при ошибках stale cleanup намеренно
  пропускается;
- `fail_safe_threshold` не заблокировал слишком массовое удаление.

## MFE не открывается

Проверьте:

- `http://localhost:3002/remoteEntry.js` доступен;
- DataHub frontend получил MFE-конфигурацию;
- remote entry URL доступен из браузера, а не только с сервера;
- в консоли браузера нет ошибок загрузки chunks.
