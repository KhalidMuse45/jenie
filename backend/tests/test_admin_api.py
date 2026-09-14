"""The administrative HTTP API.

These drive the engine the way a person will before iMessage exists, so the
golden path is exercised end to end over HTTP rather than through the services.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.database.models import Membership
from app.seed import seed, stable_id
from tests.conftest import ADMIN_TOKEN, acting_as

NEXT_WEEK = (datetime.now(UTC) + timedelta(days=7)).isoformat()


async def _cast(session):
    """Seed ColorStack UMN and commit, so the API's own sessions can see it."""
    await seed(session)
    await session.commit()

    def member(key: str):
        return session.get(Membership, stable_id("membership", "colorstack-umn", key))

    return {
        "khalid": await member("khalid"),
        "sarah": await member("sarah"),
        "izra": await member("izra"),
        "marwa": await member("marwa"),
    }


class TestAccess:
    async def test_health_needs_no_token(self, api):
        response = await api.get("/health", headers={"X-Jenie-Admin-Token": ""})

        assert response.status_code == 200

    async def test_the_api_refuses_a_missing_token(self, api, session):
        cast = await _cast(session)

        response = await api.post(
            "/work-items",
            json={"type": "INITIATIVE", "title": "Nope"},
            headers={"X-Jenie-Admin-Token": "", **acting_as(cast["khalid"])},
        )

        assert response.status_code == 401

    async def test_the_api_refuses_a_wrong_token(self, api, session):
        cast = await _cast(session)

        response = await api.post(
            "/work-items",
            json={"type": "INITIATIVE", "title": "Nope"},
            headers={"X-Jenie-Admin-Token": ADMIN_TOKEN + "x", **acting_as(cast["khalid"])},
        )

        assert response.status_code == 401

    async def test_a_request_must_say_who_it_acts_as(self, api, session):
        await _cast(session)

        response = await api.post("/work-items", json={"type": "INITIATIVE", "title": "Nope"})

        assert response.status_code == 400
        assert "X-Jenie-Actor" in response.json()["detail"]

    async def test_an_unknown_actor_is_refused(self, api, session):
        await _cast(session)

        response = await api.get(
            "/outbound-messages",
            headers={"X-Jenie-Actor": "00000000-0000-0000-0000-000000000000"},
        )

        assert response.status_code == 404


class TestTheGoldenPath:
    async def test_the_whole_flow_over_http(self, api, session):
        """President delegates, VP plans, President approves, member finishes."""
        cast = await _cast(session)
        khalid, sarah, izra, marwa = (cast["khalid"], cast["sarah"], cast["izra"], cast["marwa"])

        # The President opens an initiative and hands Marketing to Sarah.
        created = await api.post(
            "/work-items",
            json={"type": "INITIATIVE", "title": "Google AI Workshop"},
            headers=acting_as(khalid),
        )
        assert created.status_code == 201
        initiative = created.json()["data"]

        created = await api.post(
            "/work-items",
            json={
                "type": "RESPONSIBILITY",
                "title": "Marketing",
                "parent_id": initiative["id"],
                "owner_membership_id": str(sarah.id),
            },
            headers=acting_as(khalid),
        )
        marketing = created.json()["data"]
        assert marketing["short_code"].startswith("RESP-")

        # Sarah drafts a plan. Nothing is assigned yet.
        created = await api.post(
            "/delegation-plans",
            json={"scope_work_item_id": marketing["id"]},
            headers=acting_as(sarah),
        )
        assert created.status_code == 201
        plan = created.json()["data"]

        for title, assignee in [
            ("Create event flyer", izra),
            ("Publish Instagram announcement", marwa),
        ]:
            added = await api.post(
                f"/delegation-plans/{plan['id']}/items",
                json={
                    "title": title,
                    "proposed_assignee_membership_id": str(assignee.id),
                    "proposed_due_at": NEXT_WEEK,
                },
                headers=acting_as(sarah),
            )
            assert added.status_code == 201

        tree = await api.get(f"/work-items/{initiative['id']}/tree", headers=acting_as(khalid))
        assert [node["item"]["type"] for node in tree.json()["data"]] == [
            "INITIATIVE",
            "RESPONSIBILITY",
        ]

        # Sarah sends it up.
        sent = await api.post(f"/delegation-plans/{plan['id']}/submit", headers=acting_as(sarah))
        assert sent.json()["data"]["status"] == "PENDING_APPROVAL"

        # It shows up on the President's list.
        waiting = await api.get("/delegation-plans", headers=acting_as(khalid))
        assert [item["id"] for item in waiting.json()["data"]] == [plan["id"]]

        # The President approves the version they were shown.
        pending = waiting.json()["data"][0]
        decided = await api.post(
            f"/delegation-plans/{plan['id']}/approve",
            json={"expected_version": pending["version"]},
            headers=acting_as(khalid),
        )
        assert decided.status_code == 200
        outcome = decided.json()["data"]
        assert outcome["plan"]["status"] == "APPROVED"
        assert len(outcome["created_work_items"]) == 2
        assert outcome["notified"] == 3  # two assignees plus Sarah

        # The tasks are real now.
        tree = await api.get(f"/work-items/{initiative['id']}/tree", headers=acting_as(khalid))
        titles = [node["item"]["title"] for node in tree.json()["data"]]
        assert "Create event flyer" in titles

        flyer = next(
            node["item"]
            for node in tree.json()["data"]
            if node["item"]["title"] == "Create event flyer"
        )

        # Izra finishes hers.
        done = await api.post(f"/work-items/{flyer['id']}/complete", headers=acting_as(izra))
        assert done.status_code == 200
        assert done.json()["data"]["work_item"]["status"] == "COMPLETE"
        assert done.json()["data"]["changed"] is True

        # Saying so again changes nothing.
        again = await api.post(f"/work-items/{flyer['id']}/complete", headers=acting_as(izra))
        assert again.json()["data"]["changed"] is False

        # And the queue shows what Jenie is about to send.
        queue = await api.get("/outbound-messages", headers=acting_as(khalid))
        kinds = [message["message_type"] for message in queue.json()["data"]]
        assert kinds.count("ASSIGNMENT") == 2
        assert "PLAN_APPROVED" in kinds
        assert "PLAN_SUBMITTED" in kinds


class TestErrorsReadLikeSentences:
    async def test_a_refused_action_explains_itself(self, api, session):
        cast = await _cast(session)

        response = await api.post(
            "/work-items",
            json={"type": "INITIATIVE", "title": "Not yours to start"},
            headers=acting_as(cast["sarah"]),
        )

        assert response.status_code == 403
        error = response.json()["error"]
        assert error["code"] == "permission_denied"
        assert error["message"] == "Only an organization administrator can start a new initiative."

    async def test_an_impossible_transition_explains_itself(self, api, session):
        cast = await _cast(session)

        initiative = (
            await api.post(
                "/work-items",
                json={"type": "INITIATIVE", "title": "Google AI Workshop"},
                headers=acting_as(cast["khalid"]),
            )
        ).json()["data"]
        marketing = (
            await api.post(
                "/work-items",
                json={
                    "type": "RESPONSIBILITY",
                    "title": "Marketing",
                    "parent_id": initiative["id"],
                    "owner_membership_id": str(cast["khalid"].id),
                },
                headers=acting_as(cast["khalid"]),
            )
        ).json()["data"]

        response = await api.post(
            f"/work-items/{marketing['id']}/complete", headers=acting_as(cast["khalid"])
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "invalid_transition"
        assert "tasks underneath it" in response.json()["error"]["message"]

    async def test_a_badly_shaped_item_explains_itself(self, api, session):
        cast = await _cast(session)

        initiative = (
            await api.post(
                "/work-items",
                json={"type": "INITIATIVE", "title": "Google AI Workshop"},
                headers=acting_as(cast["khalid"]),
            )
        ).json()["data"]

        response = await api.post(
            "/work-items",
            json={"type": "TASK", "title": "Stray task", "parent_id": initiative["id"]},
            headers=acting_as(cast["khalid"]),
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_structure"
        assert "responsibility" in response.json()["error"]["message"]

    async def test_deciding_a_stale_plan_asks_for_another_look(self, api, session):
        cast = await _cast(session)
        khalid, sarah, izra = cast["khalid"], cast["sarah"], cast["izra"]

        initiative = (
            await api.post(
                "/work-items",
                json={"type": "INITIATIVE", "title": "Google AI Workshop"},
                headers=acting_as(khalid),
            )
        ).json()["data"]
        marketing = (
            await api.post(
                "/work-items",
                json={
                    "type": "RESPONSIBILITY",
                    "title": "Marketing",
                    "parent_id": initiative["id"],
                    "owner_membership_id": str(sarah.id),
                },
                headers=acting_as(khalid),
            )
        ).json()["data"]
        plan = (
            await api.post(
                "/delegation-plans",
                json={"scope_work_item_id": marketing["id"]},
                headers=acting_as(sarah),
            )
        ).json()["data"]
        await api.post(
            f"/delegation-plans/{plan['id']}/items",
            json={
                "title": "Create event flyer",
                "proposed_assignee_membership_id": str(izra.id),
                "proposed_due_at": NEXT_WEEK,
            },
            headers=acting_as(sarah),
        )
        submitted = (
            await api.post(f"/delegation-plans/{plan['id']}/submit", headers=acting_as(sarah))
        ).json()["data"]
        seen_version = submitted["version"]

        # The President adjusts the plan in front of them...
        item_id = submitted["items"][0]["id"]
        await api.patch(
            f"/delegation-plans/{plan['id']}/items/{item_id}",
            json={"title": "Create event flyer (final)"},
            headers=acting_as(khalid),
        )

        # ...then tries to approve the version they first read.
        response = await api.post(
            f"/delegation-plans/{plan['id']}/approve",
            json={"expected_version": seen_version},
            headers=acting_as(khalid),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "plan_changed"
        assert "another look" in response.json()["error"]["message"]

    @pytest.mark.parametrize("path", ["/work-items/{}", "/work-items/{}/tree"])
    async def test_work_in_another_organization_reads_as_missing(self, api, session, path):
        """Not 403: confirming it exists would leak another organization's shape."""
        cast = await _cast(session)
        missing = "11111111-1111-1111-1111-111111111111"

        response = await api.get(path.format(missing), headers=acting_as(cast["khalid"]))

        assert response.status_code == 404
