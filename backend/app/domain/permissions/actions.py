"""The vocabulary of things an actor can attempt.

Keeping this a closed enum is what makes the policy auditable: every action a
caller can ask about is listed here, and anything without a rule is denied.
"""

from enum import StrEnum


class Action(StrEnum):
    # Work
    CREATE_INITIATIVE = "CREATE_INITIATIVE"
    CREATE_WORK_ITEM = "CREATE_WORK_ITEM"
    VIEW_WORK_ITEM = "VIEW_WORK_ITEM"
    EDIT_WORK_ITEM = "EDIT_WORK_ITEM"
    CANCEL_WORK_ITEM = "CANCEL_WORK_ITEM"
    DELEGATE_RESPONSIBILITY = "DELEGATE_RESPONSIBILITY"

    # Task lifecycle
    START_TASK = "START_TASK"
    COMPLETE_TASK = "COMPLETE_TASK"
    BLOCK_TASK = "BLOCK_TASK"
    REASSIGN_TASK = "REASSIGN_TASK"

    # Delegation plans
    CREATE_PLAN = "CREATE_PLAN"
    EDIT_PLAN = "EDIT_PLAN"
    SUBMIT_PLAN = "SUBMIT_PLAN"
    APPROVE_PLAN = "APPROVE_PLAN"
    REJECT_PLAN = "REJECT_PLAN"

    # People and organization
    VIEW_MEMBER_WORK = "VIEW_MEMBER_WORK"
    VIEW_ORGANIZATION_WORK = "VIEW_ORGANIZATION_WORK"
    MANAGE_MEMBERS = "MANAGE_MEMBERS"
    MANAGE_HIERARCHY = "MANAGE_HIERARCHY"
