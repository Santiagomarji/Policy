"""
Edge-case & resilience tests + MemberService unit tests.

Covers the rough edges a smooth customer experience must handle gracefully:
  * malformed input (bad JSON dates, non-numeric lat/lng, missing fields)
  * empty states (member with no group/event/connections yet)
  * unplaced members (too few to form a group)
  * everyone flakes (all no-show) -> group flagged at risk
  * unknown ids -> clean 404s, not crashes
  * member self-service safety (block self, block unknown)
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from orbit.services.api import OrbitRouter
from orbit.services.json_repository import JsonFileRepository
from orbit.services.member_service import MemberService


class EdgeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "edge.json")
        self.repo = JsonFileRepository(self.path)
        self.r = OrbitRouter(self.repo)

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def club(self, min_density=6):
        _, b = self.r.handle("POST", "/clubs",
                             {"name": "C", "city": "City",
                              "min_density": min_density})
        return b["id"]

    def members(self, club_id, n):
        ids = []
        for i in range(n):
            _, b = self.r.handle("POST", f"/clubs/{club_id}/members",
                                 {"name": f"M{i}", "email": f"m{i}@x.io",
                                  "availability": "tue_pm"})
            ids.append(b["id"])
        return ids


class TestMalformedInput(EdgeBase):
    def test_bad_start_date_returns_400(self):
        club = self.club()
        s, body = self.r.handle("POST", f"/clubs/{club}/cycles",
                                {"start_date": "not-a-date"})
        self.assertEqual(s, 400)

    def test_missing_member_fields_returns_400(self):
        club = self.club()
        s, body = self.r.handle("POST", f"/clubs/{club}/members",
                                {"name": "OnlyName"})
        self.assertEqual(s, 400)
        self.assertIn("email", body["error"])

    def test_bad_latlng_returns_400(self):
        club = self.club()
        s, body = self.r.handle("POST", f"/clubs/{club}/members",
                                {"name": "N", "email": "e@x.io",
                                 "lat": "x", "lng": "y"})
        self.assertEqual(s, 400)

    def test_unknown_ids_return_404(self):
        for path in ["/clubs/nope/members", "/cycles/nope/groups",
                     "/groups/nope/events", "/events/nope",
                     "/members/nope", "/members/nope/group",
                     "/venues/nope"]:
            s, _ = self.r.handle("GET", path, None)
            self.assertEqual(s, 404, f"{path} should 404")


class TestEmptyStates(EdgeBase):
    def test_member_with_no_group_yet(self):
        club = self.club()
        ids = self.members(club, 3)  # below density, no cycle run
        me = ids[0]
        # profile works, group is None, upcoming is null, connections empty.
        s, profile = self.r.handle("GET", f"/members/{me}", None)
        self.assertEqual(s, 200)
        self.assertIsNone(profile["current_group_id"])

        s, grp = self.r.handle("GET", f"/members/{me}/group", None)
        self.assertEqual(s, 200)
        self.assertIsNone(grp["group"])
        self.assertEqual(grp["groupmates"], [])

        s, up = self.r.handle("GET", f"/members/{me}/upcoming", None)
        self.assertEqual(s, 200)
        self.assertIsNone(up["event"])

        s, conns = self.r.handle("GET", f"/members/{me}/connections", None)
        self.assertEqual(s, 200)
        self.assertEqual(conns, [])

    def test_self_rsvp_with_no_event_returns_409(self):
        club = self.club()
        ids = self.members(club, 6)
        # Run a cycle so they have a group, but create NO event.
        _, cyc = self.r.handle("POST", f"/clubs/{club}/cycles",
                               {"start_date": "2026-01-06"})
        self.r.handle("POST", f"/cycles/{cyc['id']}/commit", {"seed": 1})
        s, body = self.r.handle("POST", f"/members/{ids[0]}/rsvp", {})
        self.assertEqual(s, 409)


class TestUnplacedMembers(EdgeBase):
    def test_too_few_members_leaves_no_groups(self):
        club = self.club(min_density=3)
        self.members(club, 3)  # below TARGET_MIN of 6
        _, cyc = self.r.handle("POST", f"/clubs/{club}/cycles",
                               {"start_date": "2026-01-06"})
        s, groups = self.r.handle("POST", f"/cycles/{cyc['id']}/commit",
                                  {"seed": 1})
        self.assertEqual(s, 201)
        self.assertEqual(groups, [])  # nobody placed; no crash


class TestEveryoneFlakes(EdgeBase):
    def test_all_no_show_flags_group_at_risk(self):
        club = self.club()
        ids = self.members(club, 6)
        _, cyc = self.r.handle("POST", f"/clubs/{club}/cycles",
                               {"start_date": "2026-01-06"})
        _, groups = self.r.handle("POST", f"/cycles/{cyc['id']}/commit",
                                  {"seed": 1})
        g = groups[0]
        _, ev = self.r.handle("POST", f"/groups/{g['id']}/events",
                              {"starts_at": _future(3)})
        for mid in g["member_ids"]:
            self.r.handle("POST", f"/events/{ev['id']}/rsvp",
                          {"member_id": mid})
        # everyone no-shows
        self.r.handle("POST", f"/events/{ev['id']}/attendance",
                      {"attended": [], "no_show": g["member_ids"]})
        s, health = self.r.handle("GET", f"/cycles/{cyc['id']}/health", None)
        self.assertEqual(s, 200)
        self.assertTrue(health[0]["at_risk"])

        # and the flakers' reliability dropped
        s, profile = self.r.handle("GET", f"/members/{g['member_ids'][0]}", None)
        self.assertLess(profile["reliability_score"], 100)


class TestMemberServiceUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = JsonFileRepository(os.path.join(self.tmp, "ms.json"))
        self.ms = MemberService(self.repo)
        from orbit.services.club_service import ClubService
        self.cs = ClubService(self.repo)
        self.club = self.cs.create_club("C", "City", min_density=6)

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def test_block_self_raises_valueerror(self):
        m = self.cs.register_member(self.club.id, "A", "a@x.io")
        with self.assertRaises(ValueError):
            self.ms.block_member(m.id, m.id)

    def test_block_unknown_raises_keyerror(self):
        m = self.cs.register_member(self.club.id, "A", "a@x.io")
        with self.assertRaises(KeyError):
            self.ms.block_member(m.id, "ghost")

    def test_block_is_symmetric(self):
        a = self.cs.register_member(self.club.id, "A", "a@x.io")
        b = self.cs.register_member(self.club.id, "B", "b@x.io")
        self.ms.block_member(a.id, b.id)
        self.assertIn(b.id, self.repo.blocks[a.id])
        self.assertIn(a.id, self.repo.blocks[b.id])

    def test_current_group_none_before_rotation(self):
        m = self.cs.register_member(self.club.id, "A", "a@x.io")
        self.assertIsNone(self.ms.current_group(m.id))


def _future(days):
    return (datetime.utcnow() + timedelta(days=days)).isoformat()


if __name__ == "__main__":
    unittest.main()
