# Permissions

Every authorization decision in Jenie is made by `app/domain/permissions`.
Route handlers, the message pipeline, and the domain services ask it; none of
them check a role themselves.

A language model never participates. It can name an action — `APPROVE_PLAN` —
and nothing more. Whether that action is allowed is decided here, from the
database's view of the organization.

## Shape

```
Actor  +  Action  +  Subject   →   Decision(allowed, reason)
```

- **Actor** — who is acting, and how far their authority reaches. Built once per
  request or message by `load_actor`, which resolves the hierarchy into a
  `scope`: the actor's own membership plus everyone beneath it.
- **Action** — a closed enum. If it isn't listed, it can't be asked for.
- **Subject** — what is being acted on, as a plain value rather than an ORM row.
- **Decision** — carries a `reason` written for a person, because it is relayed
  to users verbatim over iMessage.

`can()` is a pure function. The only database work happens in `load_actor`.

## Order of checks

`can()` applies three gates before any rule runs. The order is load-bearing:

1. **Membership is active.** An inactive seat carries no authority, superadmin
   included.
2. **Subject is in the actor's organization.** This runs *before* the superadmin
   shortcut — administrator authority stops at the edge of the organization that
   granted it.
3. **Superadmin.** Allowed anything, within their own organization.

Then the rule for that action is consulted. **An action with no rule is denied.**

## Rules today

| Action | Allowed when |
| --- | --- |
| `VIEW_MEMBER_WORK` | the target is the actor, or beneath them |
| `VIEW_WORK_ITEM` | the actor is responsible for the item, or above whoever is |
| `EDIT_WORK_ITEM` | as above |
| `CANCEL_WORK_ITEM` | as above |
| `CREATE_WORK_ITEM` | the actor is responsible for the *parent*, or above whoever is |
| `START_TASK` | the actor is the assignee |
| `COMPLETE_TASK` | the actor is the assignee |
| `DELEGATE_RESPONSIBILITY` | the work is the actor's *and* the recipient reports to them |
| `CREATE_PLAN` | the actor is responsible for the responsibility being planned |
| `EDIT_PLAN` | draft: the creator. Pending: the named approver. Decided: nobody |
| `SUBMIT_PLAN` | the creator, while it is still a draft |
| `APPROVE_PLAN` | the named approver, while it is pending |
| `REJECT_PLAN` | the named approver, while it is pending |
| `CREATE_INITIATIVE` | superadmin only |
| `VIEW_ORGANIZATION_WORK` | superadmin only |
| `MANAGE_MEMBERS` | superadmin only |
| `MANAGE_HIERARCHY` | superadmin only |

Two of those are worth spelling out.

**Starting and finishing are narrower than editing.** A manager may change or
cancel a report's task, but saying it is *done* belongs to the assignee. A
superadmin can still override, as they can anywhere.

**Work with no owner follows whoever created it.** An initiative exists before
anyone is responsible for it, and authority has to rest somewhere in the
meantime.

**A plan changes hands when it is submitted.** The creator owns a draft. Once it
has been sent, the approver owns it — they can adjust a due date and then
approve, and the creator can no longer edit underneath them. Once decided, it is
closed to everyone: an approved plan is the record of what was agreed to.

`BLOCK_TASK` and `REASSIGN_TASK` remain closed — both are out of MVP scope, and
a rule for something nothing calls would be a guess rather than a policy.

## Adding a rule

1. Add the subject type to `subjects.py` if the resource is new, carrying
   `organization_id` so gate 2 can apply.
2. Write the rule as a function of `(Actor, Subject) -> Decision`. Use
   `actor.covers()` and `actor.manages()` rather than reaching for the hierarchy
   again.
3. Register it in `_RULES`.
4. Give the denial a sentence a person can act on. "You don't have permission to
   approve this plan — it needs Khalid's approval" beats "403".

## Superadmin

Authority is not hard-coded to `role_type == PRESIDENT`. It is the
`is_superadmin` flag on a membership, so the organization can move the seat
without a code change. Roles are labels for display and coarse defaults; the
engine must never branch on `role_type` alone.
