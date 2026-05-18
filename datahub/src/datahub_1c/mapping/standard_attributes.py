"""Справочник стандартных реквизитов 1С по видам объектов.

`1c-metadata-service` не отдаёт эти реквизиты, поэтому source достраивает
их локально. Они всегда идут первыми в ``schemaMetadata.fields``; прикладные
реквизиты добавляются следом.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from datahub_1c.mapping.translit import is_ascii_identifier
from datahub_1c.mapping.urn import ObjectKind


@dataclass(frozen=True)
class StandardAttribute:
    """Описатель одного стандартного реквизита."""

    field_path: str
    label_ru: str
    label_en: str
    description_ru: str
    native_data_type: str
    is_part_of_key: bool = False
    nullable: bool = False


def pick_label(attr: StandardAttribute, *, object_name: str) -> str:
    return attr.label_en if is_ascii_identifier(object_name) else attr.label_ru


# Реквизиты (по видам). Имена выверены по поведению платформы 1С.

_REF: StandardAttribute = StandardAttribute(
    field_path="Ref",
    label_ru="Ссылка",
    label_en="Ref",
    description_ru="Уникальная ссылка объекта (GUID).",
    native_data_type="УникальныйИдентификатор",
    is_part_of_key=True,
    nullable=False,
)

_CODE: StandardAttribute = StandardAttribute(
    field_path="Code",
    label_ru="Код",
    label_en="Code",
    description_ru="Код элемента справочника.",
    native_data_type="Строка",
    nullable=False,
)

_DESCRIPTION: StandardAttribute = StandardAttribute(
    field_path="Description",
    label_ru="Наименование",
    label_en="Description",
    description_ru="Наименование элемента.",
    native_data_type="Строка",
    nullable=False,
)

_DELETION_MARK: StandardAttribute = StandardAttribute(
    field_path="DeletionMark",
    label_ru="ПометкаУдаления",
    label_en="DeletionMark",
    description_ru="Признак логического удаления.",
    native_data_type="Булево",
    nullable=False,
)

_PREDEFINED: StandardAttribute = StandardAttribute(
    field_path="Predefined",
    label_ru="Предопределённый",
    label_en="Predefined",
    description_ru="Признак предопределённого элемента конфигурации.",
    native_data_type="Булево",
    nullable=False,
)

_PARENT: StandardAttribute = StandardAttribute(
    field_path="Parent",
    label_ru="Родитель",
    label_en="Parent",
    description_ru="Ссылка на родителя в иерархии справочника.",
    native_data_type="СправочникСсылка",
    nullable=False,
)

_OWNER: StandardAttribute = StandardAttribute(
    field_path="Owner",
    label_ru="Владелец",
    label_en="Owner",
    description_ru="Ссылка на владельца подчинённого справочника.",
    native_data_type="СправочникСсылка",
    nullable=False,
)

_IS_FOLDER: StandardAttribute = StandardAttribute(
    field_path="IsFolder",
    label_ru="ЭтоГруппа",
    label_en="IsFolder",
    description_ru="Признак группы (для иерархии «группы и элементы»).",
    native_data_type="Булево",
    nullable=False,
)

_NUMBER: StandardAttribute = StandardAttribute(
    field_path="Number",
    label_ru="Номер",
    label_en="Number",
    description_ru="Номер документа.",
    native_data_type="Строка",
    nullable=False,
)

_DATE: StandardAttribute = StandardAttribute(
    field_path="Date",
    label_ru="Дата",
    label_en="Date",
    description_ru="Дата документа.",
    native_data_type="Дата",
    nullable=False,
)

_POSTED: StandardAttribute = StandardAttribute(
    field_path="Posted",
    label_ru="Проведён",
    label_en="Posted",
    description_ru="Признак проведения документа.",
    native_data_type="Булево",
    nullable=False,
)

_LINE_NUMBER: StandardAttribute = StandardAttribute(
    field_path="LineNumber",
    label_ru="НомерСтроки",
    label_en="LineNumber",
    description_ru="Порядковый номер строки табличной части или записи регистра.",
    native_data_type="Число",
    is_part_of_key=True,
    nullable=False,
)

_TYPE: StandardAttribute = StandardAttribute(
    field_path="Type",
    label_ru="ТипЗначения",
    label_en="Type",
    description_ru="Тип значения характеристики.",
    native_data_type="ОписаниеТипов",
    nullable=False,
)

_PERIOD: StandardAttribute = StandardAttribute(
    field_path="Period",
    label_ru="Период",
    label_en="Period",
    description_ru="Период записи регистра.",
    native_data_type="Дата",
    is_part_of_key=True,
    nullable=False,
)

_RECORDER: StandardAttribute = StandardAttribute(
    field_path="Recorder",
    label_ru="Регистратор",
    label_en="Recorder",
    description_ru="Документ-регистратор, сформировавший запись регистра.",
    native_data_type="ДокументСсылка",
    is_part_of_key=True,
    nullable=False,
)

_ACTIVE: StandardAttribute = StandardAttribute(
    field_path="Active",
    label_ru="Активность",
    label_en="Active",
    description_ru="Признак активности записи регистра.",
    native_data_type="Булево",
    nullable=False,
)

_RECORD_TYPE: StandardAttribute = StandardAttribute(
    field_path="RecordType",
    label_ru="ВидДвижения",
    label_en="RecordType",
    description_ru="Вид движения регистра накопления (приход/расход).",
    native_data_type="ВидДвиженияНакопления",
    nullable=False,
)

_ACCOUNT_DR: StandardAttribute = StandardAttribute(
    field_path="AccountDr",
    label_ru="СчетДт",
    label_en="AccountDr",
    description_ru="Счет дебета записи регистра бухгалтерии.",
    native_data_type="ПланСчетовСсылка",
    nullable=False,
)

_ACCOUNT_CR: StandardAttribute = StandardAttribute(
    field_path="AccountCr",
    label_ru="СчетКт",
    label_en="AccountCr",
    description_ru="Счет кредита записи регистра бухгалтерии.",
    native_data_type="ПланСчетовСсылка",
    nullable=False,
)

_REGISTRATION_PERIOD: StandardAttribute = StandardAttribute(
    field_path="RegistrationPeriod",
    label_ru="ПериодРегистрации",
    label_en="RegistrationPeriod",
    description_ru="Период регистрации записи регистра расчета.",
    native_data_type="Дата",
    is_part_of_key=True,
    nullable=False,
)

_CALCULATION_TYPE: StandardAttribute = StandardAttribute(
    field_path="CalculationType",
    label_ru="ВидРасчета",
    label_en="CalculationType",
    description_ru="Вид расчета записи регистра расчета.",
    native_data_type="ПланВидовРасчетаСсылка",
    is_part_of_key=True,
    nullable=False,
)

_BEG_OF_ACTION_PERIOD: StandardAttribute = StandardAttribute(
    field_path="BegOfActionPeriod",
    label_ru="ПериодДействияНачало",
    label_en="BegOfActionPeriod",
    description_ru="Начало периода действия записи регистра расчета.",
    native_data_type="Дата",
    nullable=False,
)

_END_OF_ACTION_PERIOD: StandardAttribute = StandardAttribute(
    field_path="EndOfActionPeriod",
    label_ru="ПериодДействияКонец",
    label_en="EndOfActionPeriod",
    description_ru="Окончание периода действия записи регистра расчета.",
    native_data_type="Дата",
    nullable=False,
)


_STANDARD_ATTRS_BY_KIND: Mapping[ObjectKind, tuple[StandardAttribute, ...]] = {
    # Константа — скалярный объект; поле Value приходит из API с реальным
    # типом значения, поэтому статический стандартный реквизит здесь не задаём.
    ObjectKind.CONSTANT: (),
    ObjectKind.CATALOG: (
        _REF, _CODE, _DESCRIPTION, _DELETION_MARK, _PREDEFINED,
        _PARENT, _OWNER, _IS_FOLDER,
    ),
    ObjectKind.DOCUMENT: (
        _REF, _NUMBER, _DATE, _POSTED, _DELETION_MARK,
    ),
    ObjectKind.CHART_OF_CHARACTERISTIC_TYPES: (
        _REF, _CODE, _DESCRIPTION, _DELETION_MARK, _PREDEFINED,
        _PARENT, _IS_FOLDER, _TYPE,
    ),
    ObjectKind.CHART_OF_ACCOUNTS: (
        _REF, _CODE, _DESCRIPTION, _DELETION_MARK, _PREDEFINED,
        _PARENT, _IS_FOLDER,
    ),
    ObjectKind.CHART_OF_CALCULATION_TYPES: (
        _REF, _CODE, _DESCRIPTION, _DELETION_MARK, _PREDEFINED,
        _PARENT, _IS_FOLDER,
    ),
    ObjectKind.INFORMATION_REGISTER: (
        _PERIOD, _RECORDER, _LINE_NUMBER, _ACTIVE,
    ),
    ObjectKind.ACCUMULATION_REGISTER: (
        _PERIOD, _RECORDER, _LINE_NUMBER, _ACTIVE, _RECORD_TYPE,
    ),
    ObjectKind.ACCOUNTING_REGISTER: (
        _PERIOD, _RECORDER, _LINE_NUMBER, _ACTIVE, _RECORD_TYPE,
        _ACCOUNT_DR, _ACCOUNT_CR,
    ),
    ObjectKind.CALCULATION_REGISTER: (
        _RECORDER, _LINE_NUMBER, _ACTIVE, _REGISTRATION_PERIOD,
        _CALCULATION_TYPE, _BEG_OF_ACTION_PERIOD, _END_OF_ACTION_PERIOD,
    ),
    ObjectKind.ENUMERATION: (
        _REF,
    ),
}

# Реквизиты табличной части — одинаковы для любой родительской сущности.
_TABULAR_SECTION_ATTRS: tuple[StandardAttribute, ...] = (
    _REF,
    _LINE_NUMBER,
)


def attributes_for(kind: ObjectKind) -> Sequence[StandardAttribute]:
    """:raises KeyError: если вид не поддерживается справочником
        (это ошибка маппера: неизвестный вид не должен доходить до
        построения SchemaMetadata, он фильтруется/игнорируется на уровне
        source-плагина).
    """
    return _STANDARD_ATTRS_BY_KIND[kind]


def attributes_for_tabular_section() -> Sequence[StandardAttribute]:
    return _TABULAR_SECTION_ATTRS


def supported_kinds() -> Sequence[ObjectKind]:
    return tuple(_STANDARD_ATTRS_BY_KIND.keys())
