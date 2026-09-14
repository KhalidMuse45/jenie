"""Short, human-quotable identifiers.

A UUID cannot be typed into a text message. Work items and delegation plans each
carry a code like ``TASK-K4M2`` or ``PLAN-7QX1`` that appears in notifications
and can be quoted back: ``/done TASK-K4M2``, ``/approve PLAN-7QX1``.

The alphabet omits characters that are misread when someone copies a code off a
phone screen: no O/0, no I/1/L, and no U, which turns codes into words more
often than you would like.
"""

import secrets

from app.domain.enums import WorkItemType

ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 4

PLAN_PREFIX = "PLAN"

WORK_ITEM_PREFIXES = {
    WorkItemType.INITIATIVE: "INIT",
    WorkItemType.RESPONSIBILITY: "RESP",
    WorkItemType.TASK: "TASK",
}


def generate_code(prefix: str) -> str:
    """Return a candidate code. Uniqueness is enforced by the database."""
    suffix = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return f"{prefix}-{suffix}"


def generate_work_item_code(item_type: WorkItemType) -> str:
    return generate_code(WORK_ITEM_PREFIXES[item_type])


def generate_plan_code() -> str:
    return generate_code(PLAN_PREFIX)
