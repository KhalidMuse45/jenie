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
| `VIEW_ORGANIZATION_WORK` | superadmin only |
| `MANAGE_MEMBERS` | superadmin only |
| `MANAGE_HIERARCHY` | superadmin only |

Every other action is currently denied for non-superadmins. They are not
unimplemented — they are closed, and each opens when its resource exists:

| Action group | Opens in |
| --- | --- |
| work items, task lifecycle | the work tree milestone |
| delegation plans, approval | the delegation milestone |

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
