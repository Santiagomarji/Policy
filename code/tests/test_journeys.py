"""
End-to-end customer JOURNEY tests.

These simulate realistic, multi-step customer scenarios through the REST
router (the same path the web UI takes), exercising the whole experience:

  Journey A — a new member's first cycle: join -> get placed -> see my group
              -> see my next event -> RSVP myself -> attend -> reputation up.
  Journey B — continuity across cycles: after two cycles a member has met
              more people, and partial rotation keeps some familiar faces.
  Journey C — the "nobody hosts" safety net: a group with no owner still
              gets a fallback event so the member is never stranded.
  Journey D — safety: a member blocks someone, and the rotation never places
              them together again.
  Journey E — operator runs a full club: venue -> members -> cycle -> commit
              -> events -> attendance -> health, all green.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from orbit.services.api import OrbitRouter
from orbit.services.json_repository import JsonFileRepository


class JourneyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "journey.json")
        self.repo = JsonFileRepository(self.path)
        self.r = OrbitRouter(self.repo)

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    # --- helpers that assert success as they go ---
    def ok(self, status, expect=(200, 201)):
        self.assertIn(status, expect)

    def make_club(self, min_density=6):
        s, b = self.r.handle("POST", "/clubs",
                             {"name": "Journey Club", "city": "Austin",
                              "min_density": min_density})
        self.ok(s)
        return b["id"]

    def add_partner_venue(self, club_id):
        s, b = self.r.handle("POST", f"/clubs/{club_id}/venues",
                             {"name": "The Fallback Tavern", "partner": True,
                              "vetted": True})
        self.ok(s)
        return b["id"]

    def add_members(self, club_id, n, start=0):
        ids = []
        for i in range(start, start + n):
            s, b = self.r.handle(
                "POST", f"/clubs/{club_id}/members",
                {"name": f"Member {i:02d}", "email": f"m{i}@ex.io",
                 "availability": "tue_pm", "niche": "creatives",
                 "lat": 1.0, "lng": 1.0},
            )
            self.ok(s)
            ids.append(b["id"])
        return ids

    def run_cycle(self, club_id, start_iso, seed=1):
        s, cyc = self.r.handle("POST", f"/clubs/{club_id}/cycles",
                               {"start_date": start_iso})
        self.ok(s)
        s, groups = self.r.handle("POST", f"/cycles/{cyc['id']}/commit",
                                  {"seed": seed})
        self.ok(s)
        return cyc["id"], groups


class TestJourneyA_NewMemberFirstCycle(JourneyBase):
    def test_member_sees_group_event_and_rsvps_self(self):
        club = self.make_club()
        self.add_partner_venue(club)
        members = self.add_members(club, 6)
        cycle_id, groups = self.run_cycle(club, "2026-01-06")
        self.assertEqual(len(groups), 1)

        me = members[0]

        # 1. I can see my profile.
        s, profile = self.r.handle("GET", f"/members/{me}", None)
        self.ok(s)
        self.assertEqual(profile["current_group_name"], groups[0]["name"])

        # 2. I can see my group + groupmates.
        s, grp = self.r.handle("GET", f"/members/{me}/group", None)
        self.ok(s)
        self.assertIsNotNone(grp["group"])
        self.assertEqual(len(grp["groupmates"]), 5)  # 6 in group minus me

        # 3. An event is scheduled for my group.
        group_id = groups[0]["id"]
        s, ev = self.r.handle("POST", f"/groups/{group_id}/events",
                              {"starts_at": _future_iso(3)})
        self.ok(s)

        # 4. I can see my upcoming event.
        s, up = self.r.handle("GET", f"/members/{me}/upcoming", None)
        self.ok(s)
        self.assertIsNotNone(up["event"])

        # 5. I can RSVP myself (no need to know the event id).
        s, rsvp = self.r.handle("POST", f"/members/{me}/rsvp", {})
        self.ok(s)
        self.assertEqual(rsvp["member_id"], me)

        # 6. Attendance recorded -> my reliability + streak go up.
        s, _ = self.r.handle("POST", f"/events/{ev['id']}/attendance",
                             {"attended": [me], "no_show": []})
        self.ok(s)
        s, profile2 = self.r.handle("GET", f"/members/{me}", None)
        self.assertGreaterEqual(profile2["reliability_score"], 100)
        self.assertEqual(profile2["current_streak"], 1)


class TestJourneyB_ContinuityAcrossCycles(JourneyBase):
    def test_member_meets_more_people_over_time(self):
        club = self.make_club()
        self.add_partner_venue(club)
        members = self.add_members(club, 6)
        me = members[0]

        # Cycle 1
        self.run_cycle(club, "2026-01-06", seed=1)
        s, c1 = self.r.handle("GET", f"/members/{me}/connections", None)
        self.ok(s)
        met_after_1 = {m["id"] for m in c1}
        self.assertEqual(met_after_1, set(members[1:]))  # met the other 5

        # Grow the club and run cycle 2 -> should meet new people too.
        self.add_members(club, 6, start=6)
        self.run_cycle(club, "2026-01-20", seed=2)
        s, c2 = self.r.handle("GET", f"/members/{me}/connections", None)
        self.ok(s)
        met_after_2 = {m["id"] for m in c2}
        self.assertGreaterEqual(len(met_after_2), len(met_after_1))


class TestJourneyC_NobodyHostsSafetyNet(JourneyBase):
    def test_group_without_owner_still_gets_event(self):
        club = self.make_club()
        self.add_partner_venue(club)
        self.add_members(club, 6)
        cycle_id, groups = self.run_cycle(club, "2026-01-06")
        group_id = groups[0]["id"]

        # Simulate nobody hosting: clear the owner directly, then create event.
        self.repo.groups[group_id].owner_id = None
        self.repo.save()

        s, ev = self.r.handle("POST", f"/groups/{group_id}/events",
                              {"starts_at": _future_iso(3)})
        self.ok(s)
        self.assertTrue(ev["is_fallback"])
        self.assertIsNone(ev["owner_id"])
        self.assertIsNotNone(ev["venue_id"])  # placed at the partner venue


class TestJourneyD_BlockSafety(JourneyBase):
    def test_blocked_members_never_grouped(self):
        club = self.make_club(min_density=12)
        self.add_partner_venue(club)
        members = self.add_members(club, 12)
        a, b = members[0], members[1]

        # a blocks b before any rotation.
        s, _ = self.r.handle("POST", f"/members/{a}/block", {"other_id": b})
        self.ok(s)

        # Run several cycles; a and b must never share a group.
        for i, start in enumerate(["2026-01-06", "2026-01-20", "2026-02-03"]):
            cycle_id, groups = self.run_cycle(club, start, seed=i + 1)
            for g in groups:
                self.assertFalse(
                    a in g["member_ids"] and b in g["member_ids"],
                    f"blocked pair grouped in cycle {i}",
                )

    def test_cannot_block_self(self):
        club = self.make_club()
        members = self.add_members(club, 6)
        s, body = self.r.handle("POST", f"/members/{members[0]}/block",
                                {"other_id": members[0]})
        self.assertEqual(s, 400)


class TestJourneyE_OperatorFullRun(JourneyBase):
    def test_operator_end_to_end_all_green(self):
        club = self.make_club()
        self.add_partner_venue(club)
        members = self.add_members(club, 8)

        # density met
        s, d = self.r.handle("GET", f"/clubs/{club}/density", None)
        self.assertTrue(d["density_met"])

        cycle_id, groups = self.run_cycle(club, "2026-01-06")
        self.assertGreaterEqual(len(groups), 1)

        # every group: create event, everyone RSVPs + attends
        for g in groups:
            s, ev = self.r.handle("POST", f"/groups/{g['id']}/events",
                                  {"starts_at": _future_iso(3)})
            self.ok(s)
            for mid in g["member_ids"]:
                self.r.handle("POST", f"/events/{ev['id']}/rsvp",
                              {"member_id": mid})
            self.r.handle("POST", f"/events/{ev['id']}/attendance",
                          {"attended": g["member_ids"], "no_show": []})

        # health: no group at risk (full attendance + owners)
        s, health = self.r.handle("GET", f"/cycles/{cycle_id}/health", None)
        self.ok(s)
        self.assertTrue(all(not h["at_risk"] for h in health))


def _future_iso(days_ahead):
    return (datetime.utcnow() + timedelta(days=days_ahead)).isoformat()


if __name__ == "__main__":
    unittest.main()
