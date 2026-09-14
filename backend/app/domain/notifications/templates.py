"""Message bodies.

Deterministic templates, not generated text. A language model may eventually
phrase a *reply*, but a notification states facts -- who owns what, by when --
and a template cannot get those wrong.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


def format_due(due_at: datetime | None, timezone: str) -> str:
    """A due date as the recipient would read it, in their organization's zone.

    Timestamps are stored in UTC; converting only at the edge is what keeps
    "Thursday" meaning the same Thursday for everyone in the organization.
    """
    if due_at is None:
        return "No due date"
    local = due_at.astimezone(ZoneInfo(timezone))
    return local.strftime("%a, %b %-d")


def render_assignment(
    *,
    initiative_title: str,
    responsibility_title: str,
    task_title: str,
    short_code: str,
    due_at: datetime | None,
    timezone: str,
    delegated_by: str,
    approved_by: str,
) -> str:
    return (
        "New task\n\n"
        f"{initiative_title} -> {responsibility_title}\n"
        f"{task_title}\n"
        f"Due {format_due(due_at, timezone)}\n\n"
        f"{short_code}\n"
        f"Delegated by {delegated_by} - approved by {approved_by}\n\n"
        "Reply here when you start or finish."
    )


def render_plan_submitted(
    *, plan_code: str, responsibility_title: str, submitted_by: str, task_count: int
) -> str:
    tasks = "task" if task_count == 1 else "tasks"
    return (
        f"{submitted_by} sent you a delegation plan for {responsibility_title}.\n\n"
        f"{plan_code} - {task_count} proposed {tasks}\n\n"
        "Nothing is assigned until you approve it.\n"
        f"Reply APPROVE {plan_code} or REJECT {plan_code}."
    )


def render_plan_approved(
    *, plan_code: str, responsibility_title: str, approved_by: str, task_count: int
) -> str:
    tasks = "task" if task_count == 1 else "tasks"
    return (
        f"{approved_by} approved your {responsibility_title} plan ({plan_code}).\n\n"
        f"{task_count} {tasks} are now assigned and everyone has been told."
    )


def render_plan_rejected(
    *, plan_code: str, responsibility_title: str, rejected_by: str, comment: str | None
) -> str:
    body = (
        f"{rejected_by} did not approve your {responsibility_title} plan ({plan_code}).\n\n"
        "Nothing was assigned."
    )
    if comment:
        body += f"\n\nThey said: {comment}"
    return body
