"""Клиент и DTO для REST API сервиса метаданных 1С.

См. OpenAPI-спецификацию в `1c-metadata-service/api-spec/openapi.yaml`.
Этот пакет — тонкий клиентский слой: парсит HTTP-ответы в pydantic-модели
(:mod:`datahub_1c.api.models`) и больше ничем не занят. Преобразование в
DataHub-аспекты — задача :mod:`datahub_1c.mapping`.
"""
