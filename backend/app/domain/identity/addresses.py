"""Canonicalising messaging addresses.

The same person arrives as ``+16125551234``, ``(612) 555-1234``, and
``Khalid@Example.com``. Every one of those has to resolve to the same identity,
so addresses are normalised once on the way in and only the canonical form is
ever used as a lookup key.

Getting this wrong does not raise anything. Jenie simply stops recognising
someone and answers them as a stranger, which is why the rules here are explicit
and heavily tested rather than clever.
"""

import re

#: Applied to a bare national number. One organization, in the United States.
#:
#: A number that already carries a "+" is respected as-is, so international
#: members are fine as long as they give a fully qualified number. If bare
#: non-US numbers ever need supporting, this belongs on the organization row
#: beside ``timezone`` -- it is a property of the org, not of the deployment --
#: and the phone branch below should be swapped for ``phonenumbers``.
DEFAULT_COUNTRY_CODE = "1"

#: Apple hands addresses back with these prefixes in some payloads.
_URI_PREFIXES = ("mailto:", "tel:", "sms:", "imessage:")

#: Punctuation people put in phone numbers. Anything else -- a letter, in
#: particular -- means this is not a phone number, and stripping it silently
#: would invent a different one.
_PHONE_PUNCTUATION = set("+-(). \t ‐‑‒–—")

_MIN_PHONE_DIGITS = 7
_MAX_PHONE_DIGITS = 15  # E.164


class InvalidAddress(ValueError):
    """The value cannot be read as a phone number or an email address."""


def normalize_address(raw: str, *, default_country_code: str = DEFAULT_COUNTRY_CODE) -> str:
    """Return the canonical form of ``raw``.

    Phone numbers come back as E.164 (``+16125551234``); email addresses come
    back lowercased. Raises :class:`InvalidAddress` for anything else.
    """
    if raw is None:
        raise InvalidAddress("address is missing")

    value = _strip_uri_prefix(raw.strip())
    if not value:
        raise InvalidAddress("address is empty")

    if "@" in value:
        return _normalize_email(value)
    return _normalize_phone(value, default_country_code)


def _strip_uri_prefix(value: str) -> str:
    lowered = value.lower()
    for prefix in _URI_PREFIXES:
        if lowered.startswith(prefix):
            return value[len(prefix) :].strip()
    return value


def _normalize_email(value: str) -> str:
    local, _, domain = value.partition("@")
    if not local or not domain or "@" in domain or "." not in domain:
        raise InvalidAddress(f"not a usable email address: {value!r}")
    if any(character.isspace() for character in value):
        raise InvalidAddress(f"email address contains whitespace: {value!r}")

    # The local part is case-sensitive per RFC 5321, but no mail provider in
    # practice treats it that way and Apple matches addresses case-insensitively.
    # Lowercasing both halves is what makes the lookup key stable.
    return value.lower()


def _normalize_phone(value: str, default_country_code: str) -> str:
    stray = {c for c in value if not c.isdigit() and c not in _PHONE_PUNCTUATION}
    if stray:
        raise InvalidAddress(f"not a phone number: {value!r}")

    digits = re.sub(r"\D", "", value)
    if not digits:
        raise InvalidAddress(f"no digits in address: {value!r}")

    if value.lstrip().startswith("+"):
        if not _MIN_PHONE_DIGITS <= len(digits) <= _MAX_PHONE_DIGITS:
            raise InvalidAddress(f"not a valid international number: {value!r}")
        return f"+{digits}"

    # A bare national number. Only two shapes are accepted, because guessing at
    # anything else risks silently resolving to the wrong person.
    if len(digits) == 10:
        return f"+{default_country_code}{digits}"
    if len(digits) == 11 and digits.startswith(default_country_code):
        return f"+{digits}"

    raise InvalidAddress(f"cannot tell what number this is: {value!r}")
