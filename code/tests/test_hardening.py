"""
Tests for the hardening pass:
  * WelcomerService — onboarding assigns welcomer + buddy + welcome notes
  * RatingService — rate events (attendee-only), summary, follow-up prompts
  * Per-member auth — a member can only act as themselves
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from orbit.domain.enums import VolunteerType
from orbit.domain.models import Event, GeoPoint
from orbit.services.club_service import ClubService
from orbit.services.rating_service import RatingService
from orbit.services.repository import InMemoryRepository
from orbit.services.volunteer_service import VolunteerService
from orbit.services.welcomer_service import WelcomerService
from orbit.services.api import OrbitRouter
from orbit.services.json_repository import JsonFileRepository


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.clubs = ClubService(self.repo)
        self.club = self.clubs.create_club("H Club", "City", min_density=6)

    def members(self, n):
        return [
            self.clubs.register_member(self.club.id, f"M{i}", f"m{i}@x.io")
            for i in range(n)
        ]


class TestWelcomer(Base):
    def test_onboard_without_welcomer_still_welcomes(self):
        svc = WelcomerService(self.repo)
        first = self.clubs.register_member(self.club.id, "First", "f@x.io")
        # No other members, no welcomer -> still welcomes the newcomer.
        summary = svc.onboard(first.id)
        self.assertEqual(summary["member_id"], first.id)
        self.assertIsNone(summary["welcomer_id"])
        self.assertIsNone(summary["buddy_id"])
        self.assertEqual(summary["notifications"], 1)  # just the newcomer

    def test_onboard_assigns_buddy_and_welcomer(self):
        existing = self.members(3)
        # Make one of them the welcomer.
        vol = VolunteerService(self.repo)
        vol.assign_role(self.club.id, existing[0].id, VolunteerType.WELCOMER,
                        date.today())
        existing[1].reliability_score = 99  # buddy candidate

        svc = WelcomerService(self.repo)
        newcomer = self.clubs.register_member(self.club.id, "New", "n@x.io")
        summary = svc.onboard(newcomer.id)

        self.assertEqual(summary["welcomer_id"], existing[0].id)
        self.assertIsNotNone(summary["buddy_id"])
        self.assertNotEqual(summary["buddy_id"], newcomer.id)
        self.assertEqual(summary["notifications"], 3)  # newcomer + buddy + welcomer

    def test_needs_welcome_lists_unplaced(self):
        self.members(3)
        svc = WelcomerService(self.repo)
        # No cycle committed -> everyone needs welcome.
        self.assertEqual(len(svc.needs_welcome(self.club.id)), 3)


class TestRatings(Base):
    def _event_with_attendees(self):
        from orbit.services.event_service import EventService
        ev = Event(group_id="g", starts_at=datetime(2026, 1, 5, 19))
        self.repo.add_event(ev)
        events = EventService(self.repo)
        ppl = self.members(3)
        for m in ppl:
            events.rsvp(ev.id, m.id)
        return ev, ppl

    def test_rate_event_attendee_only(self):
        ev, ppl = self._event_with_attendees()
        svc = RatingService(self.repo)
        r = svc.rate_event(ev.id, ppl[0].id, 5, comment="great")
        self.assertEqual(r.score, 5)
        # a non-attendee cannot rate
        outsider = self.clubs.register_member(self.club.id, "Out", "o@x.io")
        with self.assertRaises(ValueError):
            svc.rate_event(ev.id, outsider.id, 4)

    def test_bad_score_rejected(self):
        ev, ppl = self._event_with_attendees()
        svc = RatingService(self.repo)
        with self.assertRaises(ValueError):
            svc.rate_event(ev.id, ppl[0].id, 6)

    def test_event_score_average(self):
        ev, ppl = self._event_with_attendees()
        svc = RatingService(self.repo)
        svc.rate_event(ev.id, ppl[0].id, 4)
        svc.rate_event(ev.id, ppl[1].id, 2)
        self.assertEqual(svc.event_score(ev.id), 3.0)
        summary = svc.event_rating_summary(ev.id)
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["average"], 3.0)

    def test_follow_ups_name_others(self):
        ev, ppl = self._event_with_attendees()
        # mark all attended
        from orbit.services.event_service import EventService
        EventService(self.repo).record_attendance(
            ev.id, [m.id for m in ppl], []
        )
        svc = RatingService(self.repo)
        notes = svc.send_follow_ups(ev.id)
        self.assertEqual(len(notes), 3)  # one per attendee
        # each body mentions someone else
        self.assertTrue(all(n.kind == "follow_up" for n in notes))


class TestPerMemberAuth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = JsonFileRepository(os.path.join(self.tmp, "auth.json"))
        # Operator token configured so the gate is active.
        self.r = OrbitRouter(self.repo, auth_token="operator")

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def _setup_club_with_member(self):
        _, club = self.r.handle("POST", "/clubs",
                                {"name": "C", "city": "X", "min_density": 6},
                                token="operator")
        _, member = self.r.handle("POST", f"/clubs/{club['id']}/members",
                                  {"name": "Sam", "email": "s@x.io"},
                                  token="operator")
        return club["id"], member

    def test_registration_returns_member_token(self):
        _, member = self._setup_club_with_member()
        self.assertIn("member_token", member)
        self.assertTrue(member["member_token"])

    def test_member_cannot_act_as_another(self):
        club_id, sam = self._setup_club_with_member()
        _, mia = self.r.handle("POST", f"/clubs/{club_id}/members",
                               {"name": "Mia", "email": "mia@x.io"},
                               token="operator")
        # Sam tries to block someone using Sam's token but on MIA's endpoint.
        status, body = self.r.handle(
            "POST", f"/members/{mia['id']}/block",
            {"other_id": sam["id"]}, token=sam["member_token"],
        )
        self.assertEqual(status, 403)

    def test_member_can_act_as_self(self):
        club_id, sam = self._setup_club_with_member()
        _, mia = self.r.handle("POST", f"/clubs/{club_id}/members",
                               {"name": "Mia", "email": "mia@x.io"},
                               token="operator")
        # Sam blocks Mia using Sam's own token on Sam's endpoint -> allowed.
        status, body = self.r.handle(
            "POST", f"/members/{sam['id']}/block",
            {"other_id": mia["id"]}, token=sam["member_token"],
        )
        self.assertEqual(status, 200)

    def test_operator_token_can_act_for_anyone(self):
        club_id, sam = self._setup_club_with_member()
        _, mia = self.r.handle("POST", f"/clubs/{club_id}/members",
                               {"name": "Mia", "email": "mia@x.io"},
                               token="operator")
        status, _ = self.r.handle(
            "POST", f"/members/{sam['id']}/block",
            {"other_id": mia["id"]}, token="operator",
        )
        self.assertEqual(status, 200)

    def test_member_token_not_leaked_in_list(self):
        club_id, sam = self._setup_club_with_member()
        status, members = self.r.handle("GET", f"/clubs/{club_id}/members",
                                        None, token="operator")
        self.assertEqual(status, 200)
        self.assertTrue(all("member_token" not in m for m in members))


if __name__ == "__main__":
    unittest.main()
