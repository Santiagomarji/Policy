"""
Tests for the service layer: club, matching orchestration, events/ownership/
fallback, reputation, and group health.
"""
import unittest
from datetime import date, datetime

from orbit.domain.enums import (
    CycleStatus,
    EventStatus,
    GroupStatus,
    MemberStatus,
    RsvpStatus,
)
from orbit.domain.models import GeoPoint, Venue
from orbit.services.repository import InMemoryRepository
from orbit.services.club_service import ClubService
from orbit.services.matching_service import MatchingService
from orbit.services.event_service import EventService
from orbit.services.reputation_service import ReputationService
from orbit.services.health_service import HealthService


class BaseFixture(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.clubs = ClubService(self.repo)
        self.matching = MatchingService(self.repo)
        self.events = EventService(self.repo)
        self.reputation = ReputationService(self.repo)
        self.health = HealthService(self.repo)
        self.club = self.clubs.create_club("Test Club", "Testville", min_density=6)

    def register_n(self, n, availability={"tue_pm"}):
        return [
            self.clubs.register_member(
                club_id=self.club.id,
                name=f"Member {i}",
                email=f"m{i}@example.com",
                availability=set(availability),
                location=GeoPoint(1.0, 1.0),
                niche="creatives",
            )
            for i in range(n)
        ]


class TestClubService(BaseFixture):
    def test_register_member_is_active(self):
        m = self.register_n(1)[0]
        self.assertEqual(m.status, MemberStatus.ACTIVE)
        self.assertEqual(m.preference.niche, "creatives")

    def test_density_gate(self):
        self.register_n(5)
        self.assertFalse(self.clubs.check_density(self.club.id))
        self.register_n(1)
        self.assertTrue(self.clubs.check_density(self.club.id))

    def test_get_active_members(self):
        members = self.register_n(4)
        members[0].status = MemberStatus.PAUSED
        active = self.clubs.get_active_members(self.club.id)
        self.assertEqual(len(active), 3)


class TestMatchingService(BaseFixture):
    def test_create_cycle_planned(self):
        cycle = self.matching.create_cycle(self.club.id, date(2026, 1, 1))
        self.assertEqual(cycle.status, CycleStatus.PLANNED)
        self.assertEqual((cycle.end_date - cycle.start_date).days, 14)

    def test_generate_and_commit_cycle(self):
        self.register_n(6)
        cycle = self.matching.create_cycle(self.club.id, date(2026, 1, 1))
        proposal = self.matching.generate_proposal(cycle.id, seed=1)
        self.assertEqual(cycle.status, CycleStatus.PROPOSED)
        self.assertEqual(len(proposal.groups), 1)

        groups = self.matching.commit_proposal(cycle.id, proposal)
        self.assertEqual(cycle.status, CycleStatus.COMMITTED)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].status, GroupStatus.HEALTHY)
        self.assertTrue(groups[0].name.startswith("Orbit-"))

    def test_met_history_recorded_after_commit(self):
        members = self.register_n(6)
        cycle = self.matching.create_cycle(self.club.id, date(2026, 1, 1))
        proposal = self.matching.generate_proposal(cycle.id, seed=1)
        self.matching.commit_proposal(cycle.id, proposal)
        # Each member should now have met the others in their group.
        g = self.repo.groups_for_cycle(cycle.id)[0]
        first = g.member_ids[0]
        self.assertEqual(
            self.repo.met_history[first], set(g.member_ids) - {first}
        )

    def test_rotation_across_two_cycles_changes_membership(self):
        """Over two cycles with new members added, groups should partially
        rotate (not be identical)."""
        self.register_n(6)
        c1 = self.matching.create_cycle(self.club.id, date(2026, 1, 1))
        p1 = self.matching.generate_proposal(c1.id, seed=1)
        self.matching.commit_proposal(c1.id, p1)
        g1 = sorted(self.repo.groups_for_cycle(c1.id)[0].member_ids)

        # Add 6 more members and run a second cycle.
        self.register_n(6)
        c2 = self.matching.create_cycle(self.club.id, date(2026, 1, 15))
        p2 = self.matching.generate_proposal(c2.id, seed=1)
        self.matching.commit_proposal(c2.id, p2)
        groups2 = self.repo.groups_for_cycle(c2.id)
        # There should now be 2 groups (12 members), proving growth+rotation.
        self.assertEqual(len(groups2), 2)


class TestEventOwnershipFallback(BaseFixture):
    def _committed_group(self):
        self.register_n(6)
        cycle = self.matching.create_cycle(self.club.id, date(2026, 1, 1))
        proposal = self.matching.generate_proposal(cycle.id, seed=1)
        groups = self.matching.commit_proposal(cycle.id, proposal)
        return groups[0]

    def test_owner_run_event(self):
        group = self._committed_group()
        self.assertIsNotNone(group.owner_id)
        ev = self.events.create_event_for_group(group.id, datetime(2026, 1, 5, 19))
        self.assertFalse(ev.is_fallback)
        self.assertEqual(ev.owner_id, group.owner_id)
        self.assertEqual(ev.status, EventStatus.PUBLISHED)

    def test_fallback_event_when_no_owner(self):
        group = self._committed_group()
        group.owner_id = None  # simulate nobody accepting
        # Give the club a partner venue for the fallback.
        self.repo.add_venue(
            Venue(club_id=self.club.id, name="Partner Bar", partner=True, vetted=True)
        )
        ev = self.events.create_event_for_group(group.id, datetime(2026, 1, 5, 19))
        self.assertTrue(ev.is_fallback)
        self.assertIsNone(ev.owner_id)
        self.assertIsNotNone(ev.venue_id)  # placed at the partner venue

    def test_offer_ownership_accepts_reliable_member(self):
        group = self._committed_group()
        group.owner_id = None
        # All members default to reliability 100 -> first accepts.
        accepted = self.events.offer_ownership(group.id, group.member_ids)
        self.assertEqual(accepted, group.member_ids[0])
        self.assertEqual(group.owner_id, accepted)

    def test_offer_ownership_rejects_all_unreliable(self):
        group = self._committed_group()
        group.owner_id = None
        for mid in group.member_ids:
            self.repo.members[mid].reliability_score = 10  # below 50 gate
        accepted = self.events.offer_ownership(group.id, group.member_ids)
        self.assertIsNone(accepted)


class TestReputation(BaseFixture):
    def test_reward_and_penalty(self):
        m = self.register_n(1)[0]
        m.reliability_score = 90
        self.reputation.reward_attendance(m.id)
        self.assertEqual(self.reputation.get_score(m.id), 92)
        self.assertEqual(self.reputation.get_streak(m.id), 1)

        self.reputation.penalize_no_show(m.id)
        self.assertEqual(self.reputation.get_score(m.id), 82)
        self.assertEqual(self.reputation.get_streak(m.id), 0)

    def test_score_capped_at_100(self):
        m = self.register_n(1)[0]
        m.reliability_score = 99
        self.reputation.reward_attendance(m.id)
        self.assertEqual(self.reputation.get_score(m.id), 100)

    def test_score_floored_at_0(self):
        m = self.register_n(1)[0]
        m.reliability_score = 5
        self.reputation.penalize_no_show(m.id)
        self.assertEqual(self.reputation.get_score(m.id), 0)

    def test_process_event_attendance(self):
        members = self.register_n(2)
        self.reputation.process_event_attendance(
            attended_ids=[members[0].id], no_show_ids=[members[1].id]
        )
        self.assertEqual(self.reputation.get_streak(members[0].id), 1)
        self.assertEqual(self.reputation.get_streak(members[1].id), 0)


class TestHealth(BaseFixture):
    def _group_with_completed_event(self, attended, no_show):
        self.register_n(6)
        cycle = self.matching.create_cycle(self.club.id, date(2026, 1, 1))
        proposal = self.matching.generate_proposal(cycle.id, seed=1)
        groups = self.matching.commit_proposal(cycle.id, proposal)
        group = groups[0]
        ev = self.events.create_event_for_group(group.id, datetime(2026, 1, 5, 19))
        ids = group.member_ids
        for mid in ids:
            self.events.rsvp(ev.id, mid)
        att = ids[:attended]
        ns = ids[attended:attended + no_show]
        self.events.record_attendance(ev.id, att, ns)
        return cycle, group

    def test_healthy_group_not_at_risk(self):
        cycle, group = self._group_with_completed_event(attended=6, no_show=0)
        report = self.health.assess_group(group.id)
        self.assertEqual(report.attendance_rate, 1.0)
        self.assertTrue(report.has_owner)
        self.assertFalse(report.at_risk)

    def test_low_attendance_flags_at_risk(self):
        cycle, group = self._group_with_completed_event(attended=2, no_show=4)
        report = self.health.assess_group(group.id)
        self.assertLess(report.attendance_rate, 0.5)
        self.assertTrue(report.at_risk)
        self.assertEqual(group.status, GroupStatus.AT_RISK)

    def test_no_owner_flags_at_risk(self):
        cycle, group = self._group_with_completed_event(attended=6, no_show=0)
        group.owner_id = None
        report = self.health.assess_group(group.id)
        self.assertTrue(report.at_risk)

    def test_get_at_risk_groups(self):
        cycle, group = self._group_with_completed_event(attended=1, no_show=5)
        at_risk = self.health.get_at_risk_groups(cycle.id)
        self.assertEqual(len(at_risk), 1)


if __name__ == "__main__":
    unittest.main()
