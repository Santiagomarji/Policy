"""
Tests for the REST API routing logic (OrbitRouter.handle).

These exercise the API without opening a socket, by calling the
transport-independent router directly. Uses a temp JSON store.
"""
import os
import tempfile
import unittest

from orbit.services.api import OrbitRouter
from orbit.services.json_repository import JsonFileRepository


class TestOrbitRouter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "api_test.json")
        self.repo = JsonFileRepository(self.path)
        self.router = OrbitRouter(self.repo)

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def _create_club(self, min_density=6):
        status, body = self.router.handle(
            "POST", "/clubs", {"name": "API Club", "city": "Netville",
                               "min_density": min_density}
        )
        self.assertEqual(status, 201)
        return body["id"]

    def _add_member(self, club_id, i):
        status, body = self.router.handle(
            "POST", f"/clubs/{club_id}/members",
            {"name": f"M{i}", "email": f"m{i}@x.io",
             "availability": ["tue_pm"], "lat": 1.0, "lng": 1.0,
             "niche": "creatives"},
        )
        self.assertEqual(status, 201)
        return body["id"]

    def test_health(self):
        status, body = self.router.handle("GET", "/health", None)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_create_and_list_clubs(self):
        cid = self._create_club()
        status, body = self.router.handle("GET", "/clubs", None)
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["id"], cid)

    def test_missing_required_field_returns_400(self):
        status, body = self.router.handle("POST", "/clubs", {"name": "X"})
        self.assertEqual(status, 400)
        self.assertIn("city", body["error"])

    def test_unknown_club_returns_404(self):
        status, body = self.router.handle(
            "GET", "/clubs/does-not-exist/density", None
        )
        self.assertEqual(status, 404)

    def test_density_endpoint(self):
        cid = self._create_club(min_density=2)
        self._add_member(cid, 0)
        status, body = self.router.handle("GET", f"/clubs/{cid}/density", None)
        self.assertEqual(status, 200)
        self.assertFalse(body["density_met"])
        self._add_member(cid, 1)
        status, body = self.router.handle("GET", f"/clubs/{cid}/density", None)
        self.assertTrue(body["density_met"])

    def test_full_flow_generate_commit_groups_health(self):
        cid = self._create_club(min_density=6)
        for i in range(6):
            self._add_member(cid, i)

        # Create a cycle.
        status, cyc = self.router.handle(
            "POST", f"/clubs/{cid}/cycles", {"start_date": "2026-01-06"}
        )
        self.assertEqual(status, 201)
        cycle_id = cyc["id"]

        # Generate (proposal only).
        status, proposal = self.router.handle(
            "POST", f"/cycles/{cycle_id}/generate", {"seed": 1}
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(proposal["groups"]), 1)

        # Commit.
        status, groups = self.router.handle(
            "POST", f"/cycles/{cycle_id}/commit", {"seed": 1}
        )
        self.assertEqual(status, 201)
        self.assertEqual(len(groups), 1)
        group_id = groups[0]["id"]

        # List groups.
        status, listed = self.router.handle(
            "GET", f"/cycles/{cycle_id}/groups", None
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(listed), 1)

        # Create an event for the group.
        status, event = self.router.handle(
            "POST", f"/groups/{group_id}/events", {"starts_at": "2026-01-10T19:00:00"}
        )
        self.assertEqual(status, 201)
        event_id = event["id"]

        # RSVP a member, then record attendance.
        member_ids = groups[0]["member_ids"]
        status, _ = self.router.handle(
            "POST", f"/events/{event_id}/rsvp", {"member_id": member_ids[0]}
        )
        self.assertEqual(status, 201)
        status, att = self.router.handle(
            "POST", f"/events/{event_id}/attendance",
            {"attended": [member_ids[0]], "no_show": []},
        )
        self.assertEqual(status, 200)

        # Health.
        status, health = self.router.handle(
            "GET", f"/cycles/{cycle_id}/health", None
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(health), 1)

    def test_persists_across_router_instances(self):
        cid = self._create_club()
        # A brand-new router on the same file should see the club.
        router2 = OrbitRouter(JsonFileRepository(self.path))
        status, body = router2.handle("GET", "/clubs", None)
        self.assertEqual(status, 200)
        self.assertEqual(body[0]["id"], cid)

    def test_no_route_returns_404(self):
        status, body = self.router.handle("GET", "/nonsense", None)
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
