"""Парсер ``ConfigDumpInfo.xml`` 1С и индекс UUID объектов метаданных.

Индекс нужен для стабильных dataset/container URN. Парсер работает потоково,
поддерживает объекты, ТЧ, пользовательские реквизиты и HTTP/Web-сервисы.
Служебные XML-узлы с id вида ``<uuid>.<n>`` игнорируются; UUID приводятся
к lowercase с сохранением дефисов.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO
from xml.etree.ElementTree import iterparse

from datahub_1c.mapping.urn import ObjectKind, spec_for

# Имя XML-тега каждой записи метаданных. iterparse даёт теги с namespace
# (``{http://v8.1c.ru/8.3/xcf/dumpinfo}Metadata``), поэтому в итерации
# мы сравниваем с локальной частью имени.
_METADATA_TAG_LOCAL: str = "Metadata"

# Регексп «чистого» UUID (8-4-4-4-12 hex с дефисами). Служебные узлы XML
# имеют id вида ``<uuid>.<n>`` (``Help``/``ManagerModule``/...) — у них суффикс
# с точкой, такие пропускаем.
_UUID_RE: re.Pattern[str] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    flags=re.IGNORECASE,
)

# Роли вложенных метаданных, которые мы трактуем как «атрибуты» уровня
# объекта (4 сегмента имени). Регистры используют ``Resource``/``Dimension``
# параллельно с ``Attribute`` — для индекса все три равнозначны: это
# потенциально пригодится для ``oneCObjectProperties.attributesUuidMap``.
_ATTRIBUTE_ROLES: frozenset[str] = frozenset({"Attribute", "Resource", "Dimension"})

# Роль контейнера ТЧ (4 сегмента имени) и роль атрибута внутри ТЧ
# (6 сегментов имени). Для контракта индекса достаточно поддержать только
# Attribute внутри ТЧ — Resource/Dimension в ТЧ не встречаются.
_TABULAR_SECTION_ROLE: str = "TabularSection"
_HTTP_SERVICE_PREFIX: str = "HTTPService"
_WEB_SERVICE_PREFIX: str = "WebService"
_HTTP_SERVICE_TYPE: str = "HTTPServices"
_WEB_SERVICE_TYPE: str = "WebServices"


def _build_eng_to_kind() -> dict[str, ObjectKind]:
    """Маппинг ENG-префикса из ``ConfigDumpInfo.xml`` в ``ObjectKind``."""
    return {spec_for(kind).english_term: kind for kind in ObjectKind}


@dataclass(frozen=True)
class MetadataUuidIndex:
    """Индекс ``(kind, name[, ts][, attr]) -> uuid``."""

    objects: dict[tuple[ObjectKind, str], str] = field(default_factory=dict)
    tabular_sections: dict[tuple[ObjectKind, str, str], str] = field(default_factory=dict)
    attributes: dict[tuple[ObjectKind, str, str | None, str], str] = field(default_factory=dict)
    integration_services: dict[tuple[str, str], str] = field(default_factory=dict)
    integration_endpoints: dict[str, str] = field(default_factory=dict)

    def object_uuid(self, kind: ObjectKind, name: str) -> str | None:
        """UUID объекта или ``None``, если объекта нет в индексе."""
        return self.objects.get((kind, name))

    def tabular_section_uuid(
        self,
        kind: ObjectKind,
        name: str,
        ts_name: str,
    ) -> str | None:
        """UUID табличной части или ``None``."""
        return self.tabular_sections.get((kind, name, ts_name))

    def attribute_uuid(
        self,
        kind: ObjectKind,
        name: str,
        ts_name: str | None,
        attr_name: str,
    ) -> str | None:
        """UUID реквизита (объекта или ТЧ), либо ``None``."""
        return self.attributes.get((kind, name, ts_name, attr_name))

    def integration_service_uuid(self, service_type: str, name: str) -> str | None:
        """UUID HTTP/Web-сервиса или ``None``."""
        return self.integration_services.get((service_type, name))

    def integration_endpoint_uuid(self, full_name: str) -> str | None:
        """UUID HTTP method / WebService operation или ``None``."""
        return self.integration_endpoints.get(full_name)


def _strip_namespace(tag: str) -> str:
    """Убрать XML-namespace у тега: ``{ns}Metadata`` → ``Metadata``."""
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag


def _normalize_uuid(raw: str) -> str | None:
    if not raw:
        return None
    candidate = raw.lower()
    if _UUID_RE.match(candidate) is None:
        return None
    return candidate


def _ingest_metadata_entry(
    *,
    name: str,
    uuid: str,
    eng_to_kind: dict[str, ObjectKind],
    index: MetadataUuidIndex,
) -> None:
    """Разложить одну запись ``<Metadata name=... id=.../>`` в индекс.

    Логика по числу сегментов имени:

    * 2 сегмента (``<Prefix>.<Name>``) → объект.
    * 4 сегмента, роль ``TabularSection`` → ТЧ; роль ``Attribute``/
      ``Resource``/``Dimension`` → атрибут уровня объекта; иные роли
      (``StandardAttribute``/``Form``/``Command``/...) — игнор.
    * 6 сегментов, центральная роль ``TabularSection`` и финальная роль
      ``Attribute`` → атрибут ТЧ. Иные комбинации — игнор.
    """
    parts = name.split(".")
    prefix = parts[0]
    if prefix in {_HTTP_SERVICE_PREFIX, _WEB_SERVICE_PREFIX}:
        _ingest_integration_service_entry(name=name, uuid=uuid, index=index)
        return

    kind = eng_to_kind.get(prefix)
    if kind is None:
        return  # незнакомый вид — пока не входит в ObjectKind

    if len(parts) == 2:
        index.objects[(kind, parts[1])] = uuid
        return

    if len(parts) == 4:
        obj_name, role, sub_name = parts[1], parts[2], parts[3]
        if role == _TABULAR_SECTION_ROLE:
            index.tabular_sections[(kind, obj_name, sub_name)] = uuid
            return
        if role in _ATTRIBUTE_ROLES:
            index.attributes[(kind, obj_name, None, sub_name)] = uuid
        return

    if len(parts) == 6:
        obj_name, ts_role, ts_name, attr_role, attr_name = (
            parts[1],
            parts[2],
            parts[3],
            parts[4],
            parts[5],
        )
        if ts_role == _TABULAR_SECTION_ROLE and attr_role in _ATTRIBUTE_ROLES:
            index.attributes[(kind, obj_name, ts_name, attr_name)] = uuid
        return


def _ingest_integration_service_entry(
    *,
    name: str,
    uuid: str,
    index: MetadataUuidIndex,
) -> None:
    """Индексировать HTTP/Web service nodes из ``ConfigDumpInfo.xml``."""
    parts = name.split(".")
    prefix = parts[0]
    if prefix == _HTTP_SERVICE_PREFIX:
        if len(parts) == 2:
            index.integration_services[(_HTTP_SERVICE_TYPE, parts[1])] = uuid
            return
        if len(parts) == 6 and parts[2] == "URLTemplate" and parts[4] == "Method":
            index.integration_endpoints[name] = uuid
        return

    if prefix == _WEB_SERVICE_PREFIX:
        if len(parts) == 2:
            index.integration_services[(_WEB_SERVICE_TYPE, parts[1])] = uuid
            return
        if len(parts) == 4 and parts[2] == "Operation":
            index.integration_endpoints[name] = uuid
        return


def _iter_metadata_entries(source: str | Path | IO[bytes]) -> Iterator[tuple[str, str]]:
    """Yield ``(name, raw_id)`` для каждой ``<Metadata>``-ноды в XML.

    Использует ``iterparse`` (только ``end``-события), очищая узлы сразу
    после обработки — для XML на ~10 МБ потребление памяти получается
    плоским (десятки МБ), а не пропорциональным размеру файла.
    """
    for _event, elem in iterparse(source, events=("end",)):
        if _strip_namespace(elem.tag) != _METADATA_TAG_LOCAL:
            continue
        name = elem.get("name") or ""
        raw_id = elem.get("id") or ""
        yield name, raw_id
        elem.clear()


def parse_config_dump_info(source: str | Path | IO[bytes]) -> MetadataUuidIndex:
    """Прочитать ``ConfigDumpInfo.xml`` и вернуть ``MetadataUuidIndex``."""
    eng_to_kind = _build_eng_to_kind()
    index = MetadataUuidIndex()

    for name, raw_id in _iter_metadata_entries(source):
        if not name:
            continue
        uuid = _normalize_uuid(raw_id)
        if uuid is None:
            # Служебный узел (id вида `<uuid>.<n>`) или вообще без id —
            # пропускаем без логирования: их в файле большинство.
            continue
        _ingest_metadata_entry(
            name=name,
            uuid=uuid,
            eng_to_kind=eng_to_kind,
            index=index,
        )

    return index


def supported_eng_prefixes() -> Iterable[str]:
    """Список ENG-префиксов, которые умеет распознавать парсер.

    Удобно для логов и диагностических сообщений (например, при пустом
    индексе можно подсказать пользователю, какие префиксы ожидались).
    Источник истины — `_KIND_SPECS` (`mapping/urn.py`).
    """
    return tuple(spec_for(kind).english_term for kind in ObjectKind) + (
        _HTTP_SERVICE_PREFIX,
        _WEB_SERVICE_PREFIX,
    )
