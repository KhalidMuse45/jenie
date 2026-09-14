"""Walking the work tree.

Same shape as the organization hierarchy, same cycle guard, same reasoning: a
parent pointer can be moved, nothing in the schema prevents a loop, and an
unguarded recursive query would hang rather than fail.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import WorkItem

MAX_DEPTH = 16

_SUBTREE = text("""
    WITH RECURSIVE tree AS (
        SELECT w.id, w.parent_id, 0 AS depth, ARRAY[w.id] AS path
        FROM work_items w
        WHERE w.id = CAST(:root_id AS uuid)

        UNION ALL

        SELECT child.id, child.parent_id, tree.depth + 1, tree.path || child.id
        FROM work_items child
        JOIN tree ON child.parent_id = tree.id
        WHERE NOT child.id = ANY(tree.path)
          AND tree.depth < :max_depth
    )
    SELECT id, depth FROM tree ORDER BY depth, id
""")

_ANCESTORS = text("""
    WITH RECURSIVE chain AS (
        SELECT w.id, w.parent_id, 0 AS depth, ARRAY[w.id] AS path
        FROM work_items w
        WHERE w.id = CAST(:root_id AS uuid)

        UNION ALL

        SELECT parent.id, parent.parent_id, chain.depth + 1, chain.path || parent.id
        FROM work_items parent
        JOIN chain ON chain.parent_id = parent.id
        WHERE NOT parent.id = ANY(chain.path)
          AND chain.depth < :max_depth
    )
    SELECT id, depth FROM chain WHERE depth > 0 ORDER BY depth
""")


@dataclass(frozen=True, slots=True)
class Node:
    item: WorkItem
    depth: int


async def subtree(session: AsyncSession, root_id: uuid.UUID) -> list[Node]:
    """The item and everything beneath it, shallowest first.

    Unlike ``OrgGraph.descendants``, this *includes* the root: callers here are
    almost always rendering or totalling a whole branch.
    """
    return await _load(session, _SUBTREE, root_id)


async def ancestors(session: AsyncSession, work_item_id: uuid.UUID) -> list[Node]:
    """The chain of parents above an item, nearest first."""
    return await _load(session, _ANCESTORS, work_item_id)


async def _load(session: AsyncSession, statement, root_id: uuid.UUID) -> list[Node]:
    rows = (await session.execute(statement, {"root_id": root_id, "max_depth": MAX_DEPTH})).all()
    if not rows:
        return []

    depths = {row.id: row.depth for row in rows}
    items = (await session.scalars(select(WorkItem).where(WorkItem.id.in_(depths)))).all()

    nodes = [Node(item=item, depth=depths[item.id]) for item in items]
    nodes.sort(key=lambda node: (node.depth, node.item.title))
    return nodes
