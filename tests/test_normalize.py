import pytest

from pipeline.normalize import canonical_property_type, normalize_currency
from scrapers.base import PropertyItem


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("USD", "USD"),
        ("US$", "USD"),
        ("u$s", "USD"),
        ("U$D 85000 /", "USD"),
        ("Dólares", "USD"),
        ("ARS", "ARS"),
        ("$", "ARS"),
        ("Pesos", "ARS"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_normalize_currency(raw, expected):
    assert normalize_currency(raw) == expected


def test_normalize_currency_keeps_unknown_values_instead_of_dropping_them():
    assert normalize_currency(" eur ") == "EUR"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("casa", "house"),
        ("CASA", "house"),
        ("Casa", "house"),
        ("casa_duplex", "house"),
        ("casa_triplex", "house"),
        ("chalet", "house"),
        ("DUPLEX / TRIPLEX", "house"),
        ("Dúplex", "house"),
        ("departamento_estandar", "apartment"),
        ("departamento_monoambiente", "apartment"),
        ("DEPARTAMENTO", "apartment"),
        ("departamento_duplex", "apartment"),
        ("departamento_penthouse", "apartment"),
        ("monoambiente", "apartment"),
        ("ph", "ph"),
        ("PHs", "ph"),
        ("casa en ph", "ph"),
        ("terrenos_y_lotes", "land"),
        ("LOTE", "land"),
        ("lote / fracción", "land"),
        ("terreno o lote", "land"),
        ("local", "retail"),
        ("locales comerciales", "retail"),
        ("oficina", "office"),
        ("consultorio", "office"),
        ("cochera", "garage"),
        ("garaje", "garage"),
        ("galpon", "warehouse"),
        ("galpón", "warehouse"),
        ("galpón", "warehouse"),  # decomposed accent variant also present in the DB
        ("depósito", "warehouse"),
        ("quinta", "weekend_house"),
        ("casa quinta", "weekend_house"),
        ("campo", "farm"),
        ("chacra", "farm"),
    ],
)
def test_canonical_property_type(raw, expected):
    assert canonical_property_type(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "otros",
        "fondo_de_comercio",
        "2 ambientes",
        "apto credito",
        "casa, departamento, local",
        "departamento, ph",
    ],
)
def test_canonical_property_type_returns_none_for_unknown_or_ambiguous(raw):
    assert canonical_property_type(raw) is None


def test_multi_value_type_resolves_when_all_parts_agree():
    assert canonical_property_type("casa, chalet") == "house"
    assert canonical_property_type("lote, terreno") == "land"


def test_property_item_normalizes_currency_on_ingest():
    item = PropertyItem(
        source="test",
        source_id="1",
        operation="sale",
        currency="US$",
        expenses_currency="$",
    )
    assert item.currency == "USD"
    assert item.expenses_currency == "ARS"
