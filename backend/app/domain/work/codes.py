"""Short, human-quotable identifiers for work items.

A UUID cannot be typed into a text message. Every work item carries a code like
``TASK-K4M2`` that appears in notifications and can be quoted back:
``/done TASK-K4M2``.

The alphabet omits characters that are misread when someone copies a code off a
phone screen: no O/0, no I/1/L, no U (which turns codes into words more often
than you would like).
"""

import secrets

from app.domain.enums import WorkItemType

ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 4

PREFIXES = {
    WorkItemType.INITIATIVE: "INIT",
    WorkItemType.RESPONSIBILITY: "RESP",
    WorkItemType.TASK: "TASK",
}


def generate_code(item_type: WorkItemType) -> str:
    """Return a candidate code. Uniqueness is enforced by the database."""
    suffix = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return f"{PREFIXES[item_type]}-{suffix}"
