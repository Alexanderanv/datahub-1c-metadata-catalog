# Установка расширения DataHub

## Требования

- DataHub 1.5.0.x.
- Python 3.11 для runner загрузки.
- DataHub GMS должен быть доступен с машины или контейнера, где выполняется
  загрузка.
- Сервис метаданных 1С должен быть доступен с машины или контейнера, где
  выполняется загрузка.
- `ConfigDumpInfo.xml` должен быть выгружен из той же конфигурации 1С.

Все команды ниже выполняются из корня репозитория.

## Установка source-коннектора

Для локального запуска:

```bash
python3.11 -m venv datahub/.venv
datahub/.venv/bin/python -m pip install -U pip
datahub/.venv/bin/python -m pip install -e "./datahub[postgres]"
```

Пакет регистрирует тип источника DataHub:

```yaml
source:
  type: 1c-enterprise
```

## Установка кастомной метамодели

Самый простой вариант из корня репозитория:

```bash
make custom-models.install
```

Если локальный Gradle не установлен, Makefile соберёт модель через Docker
образ `gradle:8.9-jdk17`.

Ручной вариант:

```bash
cd custom-models
gradle build
unzip -o build/dist/custom-models.zip -d ~/.datahub/plugins/models/
cd ..
```

После распаковки перезапустите GMS способом, принятым в вашей установке
DataHub. Затем проверьте, что DataHub GMS загрузил модель:

```bash
datahub/.venv/bin/python datahub/scripts/check_custom_models.py --server "$DATAHUB_GMS_URL"
```

Если GMS требует авторизацию:

```bash
datahub/.venv/bin/python datahub/scripts/check_custom_models.py \
  --server "$DATAHUB_GMS_URL" \
  --token "$DATAHUB_GMS_TOKEN"
```

После распаковки должна получиться структура `custom-onec/0.1.0`.

Если кастомная метамодель не установлена, укажите:

```text
ONEC_EMIT_CUSTOM_ASPECTS=false
```

В этом режиме загрузка будет использовать только стандартные аспекты DataHub.

## Опциональный MFE

MFE не нужен для загрузки данных. Он добавляет в DataHub отдельную страницу для
просмотра метаданных 1С. Подробнее: [MFE](mfe.md).
