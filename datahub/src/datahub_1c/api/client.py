"""Синхронный REST-клиент к сервису метаданных 1С.

Клиент валидирует ответы pydantic-моделями. 404 на ``/tabular-parts``
трактуется как отсутствие табличных частей.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import requests

from datahub_1c.api.models import (
    DbMapping,
    HealthResponse,
    IntegrationService,
    LineageEdge,
    MetadataObjectDetail,
    MetadataObjectSummary,
    Reference,
    TabularPart,
)

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT_SECONDS: float = 30.0


class OneCApiError(RuntimeError):
    """Ошибка уровня приложения при работе с API 1С.

    Используется, чтобы source-плагин отличал ошибки своего REST-клиента
    от случайных ``RuntimeError`` из SDK/библиотек.
    """


class OneCApiClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = session or requests.Session()
        self._owns_session = session is None
        # 1С разрешает кириллицу в логине ("Администратор"), а стандартный
        # requests.auth.HTTPBasicAuth кодирует credentials в latin-1 —
        # падает UnicodeEncodeError. Формируем заголовок вручную в UTF-8
        # (RFC 7617 допускает, современный 1C HTTP-сервис принимает).
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        self._session.headers["Authorization"] = f"Basic {token}"

    def __enter__(self) -> OneCApiClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._base_url}{path}"

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = self._url(path)
        logger.debug("GET %s params=%s", url, params)
        resp = self._session.get(url, params=params, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def health(self) -> HealthResponse:
        return HealthResponse.model_validate(self._get_json("/health"))

    def list_objects(
        self,
        *,
        types: list[str] | None = None,
    ) -> list[MetadataObjectSummary]:
        params = {"types": ",".join(types)} if types else None
        data = self._get_json("/objects", params=params)
        return [MetadataObjectSummary.model_validate(item) for item in data]

    def get_object_detail(
        self,
        object_type: str,
        name: str,
    ) -> MetadataObjectDetail:
        return MetadataObjectDetail.model_validate(self._get_json(f"/objects/{object_type}/{name}"))

    def get_tabular_parts(
        self,
        object_type: str,
        name: str,
    ) -> list[TabularPart]:
        url = self._url(f"/objects/{object_type}/{name}/tabular-parts")
        resp = self._session.get(url, timeout=self._timeout)
        if resp.status_code == 404:
            logger.debug("tabular-parts %s/%s: 404 → []", object_type, name)
            return []
        resp.raise_for_status()
        return [TabularPart.model_validate(item) for item in resp.json()]

    def get_references(
        self,
        *,
        types: list[str] | None = None,
        objects: list[str] | None = None,
        level: str = "tables",
    ) -> list[Reference]:
        params: dict[str, Any] = {"level": level}
        if types:
            params["types"] = ",".join(types)
        if objects:
            params["objects"] = ",".join(objects)
        data = self._get_json("/references", params=params)
        return [Reference.model_validate(item) for item in data]

    def get_lineage(
        self,
        *,
        objects: list[str] | None = None,
        kinds: list[str] | None = None,
    ) -> list[LineageEdge]:
        params: dict[str, Any] = {}
        if objects:
            params["objects"] = ",".join(objects)
        if kinds:
            params["kinds"] = ",".join(kinds)
        data = self._get_json("/lineage", params=params or None)
        return [LineageEdge.model_validate(item) for item in data]

    def get_integration_services(
        self,
        *,
        types: list[str] | None = None,
        services: list[str] | None = None,
        endpoints: list[str] | None = None,
    ) -> list[IntegrationService]:
        params: dict[str, Any] = {}
        if types:
            params["types"] = ",".join(types)
        if services:
            params["services"] = ",".join(services)
        if endpoints:
            params["endpoints"] = ",".join(endpoints)
        data = self._get_json("/integration-services", params=params or None)
        return [IntegrationService.model_validate(item) for item in data]

    def get_db_mapping(
        self,
        object_type: str,
        name: str,
    ) -> DbMapping:
        return DbMapping.model_validate(self._get_json(f"/db-mapping/{object_type}/{name}"))
