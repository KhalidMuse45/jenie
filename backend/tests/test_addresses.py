"""Address canonicalisation.

A mistake here is silent: Jenie simply fails to recognise someone.
"""

import pytest

from app.domain.identity import InvalidAddress, normalize_address


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The same US number, written the ways people actually write it.
        ("6125550101", "+16125550101"),
        ("612-555-0101", "+16125550101"),
        ("(612) 555-0101", "+16125550101"),
        ("612.555.0101", "+16125550101"),
        ("612 555 0101", "+16125550101"),
        ("16125550101", "+16125550101"),
        ("1 (612) 555-0101", "+16125550101"),
        ("+16125550101", "+16125550101"),
        ("+1 612 555 0101", "+16125550101"),
        ("  +1-612-555-0101  ", "+16125550101"),
        # Non-breaking space and en dash, which copy-paste drags in.
        ("+1 612–555–0101", "+16125550101"),
    ],
)
def test_phone_numbers_become_e164(raw, expected):
    assert normalize_address(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+442071838750", "+442071838750"),
        ("+44 20 7183 8750", "+442071838750"),
        ("+81 3 1234 5678", "+81312345678"),
    ],
)
def test_international_numbers_are_respected_when_fully_qualified(raw, expected):
    assert normalize_address(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("khalid@example.com", "khalid@example.com"),
        ("Khalid@Example.com", "khalid@example.com"),
        ("  KHALID@EXAMPLE.COM  ", "khalid@example.com"),
        ("khalid.muse+jenie@example.co.uk", "khalid.muse+jenie@example.co.uk"),
    ],
)
def test_email_addresses_are_lowercased(raw, expected):
    assert normalize_address(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mailto:Khalid@Example.com", "khalid@example.com"),
        ("tel:+16125550101", "+16125550101"),
        ("imessage:6125550101", "+16125550101"),
    ],
)
def test_uri_prefixes_are_stripped(raw, expected):
    assert normalize_address(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        None,
        "not an address",
        "1-800-FLOWERS",  # letters would vanish and invent a different number
        "@example.com",
        "khalid@",
        "khalid@localhost",
        "khalid @example.com",
        "+1234",  # too short for E.164
        "+1234567890123456",  # too long for E.164
        "612555010",  # nine digits: ambiguous, and guessing picks a stranger
        "0016125550101",  # international access prefix, not supported
    ],
)
def test_unusable_addresses_are_refused(raw):
    with pytest.raises(InvalidAddress):
        normalize_address(raw)


@pytest.mark.parametrize(
    "raw",
    ["6125550101", "(612) 555-0101", "Khalid@Example.com", "+442071838750"],
)
def test_normalisation_is_idempotent(raw):
    """Re-normalising a stored value must not change it.

    Every lookup key in the database has been through this function; if a second
    pass moved the value, stored rows would stop matching live traffic.
    """
    once = normalize_address(raw)

    assert normalize_address(once) == once


def test_the_default_country_code_can_be_overridden():
    assert normalize_address("2071838750", default_country_code="44") == "+442071838750"
