"""Organization hierarchy traversal.

The tree is an adjacency list: every membership points at its manager. That is
enough for the questions Jenie actually asks -- who reports to whom, who may
assign this person, who receives an escalation -- and PostgreSQL answers all of
them with recursive CTEs. A graph database would buy nothing here.

Every walk carries a ``path`` array and refuses to revisit a membership it has
already seen. A single bad manager pointer is enough to create a cycle, and
without the guard the query does not return an error, it never returns at all.
``MAX_DEPTH`` is a second, cruder backstop.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_DEPTH = 32

_DESCENDANTS = text("""
    WITH RECURSIVE tree AS (
        SELECT m.id, m.manager_membership_id, 0 AS depth, ARRAY[m.id] AS path
        FROM memberships m
        WHERE m.id = CAST(:root_id AS uuid)

        UNION ALL

        SELECT child.id,
               child.manager_membership_id,
               tree.depth + 1,
               tree.path || child.id
        FROM memberships child
        JOIN tree ON child.manager_membership_id = tree.id
        WHERE NOT child.id = ANY(tree.path)
          AND tree.depth < :max_depth
    )
    SELECT id, depth FROM tree WHERE depth > 0 ORDER BY depth, id
""")

_ANCESTORS = text("""
    WITH RECURSIVE chain AS (
        SELECT m.id, m.manager_membership_id, 0 AS depth, ARRAY[m.id] AS path
        FROM memberships m
        WHERE m.id = CAST(:root_id AS uuid)

        UNION ALL

        SELECT parent.id,
               parent.manager_membership_id,
               chain.depth + 1,
               chain.path || parent.id
        FROM memberships parent
        JOIN chain ON chain.manager_membership_id = parent.id
        WHERE NOT parent.id = ANY(chain.path)
          AND chain.depth < :max_depth
    )
    SELECT id, depth FROM chain WHERE depth > 0 ORDER BY depth
""")

_DIRECT_REPORTS = text("""
    SELECT id FROM memberships
    WHERE manager_membership_id = CAST(:manager_id AS uuid)
    ORDER BY id
""")


@dataclass(frozen=True, slots=True)
class Related:
    """A membership reached from some starting point, and how far away it is."""

    membership_id: uuid.UUID
    depth: int


class OrgGraph:
    """Hierarchy queries for one session.

    Results are structural and include inactive memberships. Filtering by status
    is a policy decision that belongs to the caller -- an inactive VP still owns
    a branch of the tree, and dropping them would silently reparent their reports.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def descendants(self, membership_id: uuid.UUID) -> list[Related]:
        """Everyone below ``membership_id``, nearest first. Excludes itself."""
        result = await self._session.execute(
            _DESCENDANTS, {"root_id": membership_id, "max_depth": MAX_DEPTH}
        )
        return [Related(row.id, row.depth) for row in result]

    async def ancestors(self, membership_id: uuid.UUID) -> list[Related]:
        """The management chain above ``membership_id``, nearest first."""
        result = await self._session.execute(
            _ANCESTORS, {"root_id": membership_id, "max_depth": MAX_DEPTH}
        )
        return [Related(row.id, row.depth) for row in result]

    async def direct_reports(self, membership_id: uuid.UUID) -> list[uuid.UUID]:
        result = await self._session.execute(_DIRECT_REPORTS, {"manager_id": membership_id})
        return [row.id for row in result]

    async def is_ancestor(self, ancestor_id: uuid.UUID, descendant_id: uuid.UUID) -> bool:
        """Whether ``ancestor_id`` sits anywhere above ``descendant_id``.

        Walks up from the descendant rather than down from the ancestor: the
        chain upward is at most the depth of the tree, while the subtree below a
        senior membership can be the entire organization.
        """
        if ancestor_id == descendant_id:
            return False
        return any(rel.membership_id == ancestor_id for rel in await self.ancestors(descendant_id))

    async def scope_ids(self, membership_id: uuid.UUID) -> set[uuid.UUID]:
        """The membership plus everyone beneath it.

        This is the set a manager may normally see and act on, and it is what
        the permission engine will consult in PR 3.
        """
        below = await self.descendants(membership_id)
        return {membership_id} | {rel.membership_id for rel in below}
