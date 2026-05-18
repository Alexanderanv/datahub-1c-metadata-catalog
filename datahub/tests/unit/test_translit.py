from __future__ import annotations

import logging

import pytest

from datahub_1c.mapping.translit import is_ascii_identifier, transliterate


class TestIsAsciiIdentifier:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Nomenklatura", True),
            ("Catalog_Nomenklatura", True),
            ("Doc123", True),
            ("Номенклатура", False),
            ("Incoming Goods", False),
            ("", False),
            ("with-dash", False),
        ],
    )
    def test_detects_ascii_identifier(self, name: str, expected: bool) -> None:
        assert is_ascii_identifier(name) is expected


class TestTransliterate:
    @pytest.mark.parametrize(
        "src,expected",
        [
            ("Номенклатура", "Nomenklatura"),
            ("Поступление", "Postuplenie"),
            ("ПоступлениеТоваров", "PostuplenieTovarov"),
            ("Состав", "Sostav"),
            ("Документ", "Dokument"),
            ("Справочник", "Spravochnik"),
        ],
    )
    def test_basic_camel_case(self, src: str, expected: str) -> None:
        assert transliterate(src) == expected

    @pytest.mark.parametrize(
        "src,expected",
        [
            ("Ёлка", "YOlka"),
            ("Объект", "Obekt"),
            ("День", "Den"),
            ("Съезд", "Sezd"),
            ("Южный", "Yuzhnyj"),
            ("Ярмарка", "Yarmarka"),
            ("Щит", "SHHit"),
            ("Часть", "CHast"),
            ("Шкаф", "SHkaf"),
            ("Цена", "CZena"),
            ("Характеристика", "Harakteristika"),
            ("Журнал", "ZHurnal"),
        ],
    )
    def test_cyrtranslit_outputs_and_cleaned_sign_markers(
        self,
        src: str,
        expected: str,
    ) -> None:
        assert transliterate(src) == expected

    def test_preserves_case(self) -> None:
        assert transliterate("Поступление") == "Postuplenie"
        assert transliterate("поступление") == "postuplenie"

    def test_mixed_ascii_and_cyrillic(self) -> None:
        assert transliterate("Доп1Поле") == "Dop1Pole"

    @pytest.mark.parametrize(
        "name",
        [
            "Nomenklatura",
            "Catalog_Goods",
            "Document_Invoice_2024",
        ],
    )
    def test_en_config_passthrough(self, name: str) -> None:
        """EN-конфигурации 1С: имя уже ASCII — отдаём как есть."""
        assert transliterate(name) == name

    def test_overrides_take_precedence(self) -> None:
        """Override применяется даже если имя транслитерируется нормально."""
        overrides = {"ПоступлениеТоваров": "GoodsReceipt"}
        assert transliterate("ПоступлениеТоваров", overrides=overrides) == "GoodsReceipt"

    def test_override_key_must_match_whole(self) -> None:
        """Override срабатывает только по полному совпадению имени, не подстроке."""
        overrides = {"Поступление": "Arrival"}
        assert transliterate("ПоступлениеТоваров", overrides=overrides) == "PostuplenieTovarov"

    def test_override_with_ascii_key(self) -> None:
        """Override может переопределить и ASCII-имя (например, ребрендинг)."""
        overrides = {"OldName": "NewName"}
        assert transliterate("OldName", overrides=overrides) == "NewName"

    def test_invalid_override_value_rejected(self) -> None:
        overrides = {"ПоступлениеТоваров": "Goods Receipt"}
        with pytest.raises(ValueError, match=r"must match \^\[A-Za-z0-9_\]\+\$"):
            transliterate("ПоступлениеТоваров", overrides=overrides)

    def test_empty_string(self) -> None:
        assert transliterate("") == ""

    def test_unknown_non_ascii_char_replaced_with_underscore(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Неизвестный не-ASCII символ заменяется на '_' с предупреждением в лог."""
        with caplog.at_level(logging.WARNING, logger="datahub_1c.mapping.translit"):
            result = transliterate("Товар№1")
        assert result == "Tovar_1"
        assert any("не распознан" in rec.message for rec in caplog.records)
