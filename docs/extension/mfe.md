# MFE

Опциональный MFE находится в:

```text
onec-metadata-explorer-mfe/
```

Он добавляет в DataHub страницу только для чтения, ориентированную на
метаданные 1С. Эта страница удобна для навигации и проверки, но загрузка
данных от неё не зависит.

## Локальная сборка

```bash
cd onec-metadata-explorer-mfe
npm run typecheck
npm run build
```

## Статический сервер демонстрационного контура

```bash
cd deploy/reference
docker compose --env-file .env \
  -f compose.yaml \
  -f compose.mfe.yaml \
  --profile mfe \
  up -d onec-metadata-explorer-mfe
```

Remote entry:

```text
http://localhost:3002/remoteEntry.js
```

Зарегистрируйте этот remote entry в MFE-конфигурации DataHub frontend.
MFE-конфигурацию нужно смонтировать или включить в образ DataHub frontend
обычным для вашей установки способом.
