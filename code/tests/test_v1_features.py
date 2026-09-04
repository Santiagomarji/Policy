"""
Tests for the 5 V1 features:
  * BigEventService     — capacity, waitlist, promotion, backup host
  * VolunteerService    — terms, expiring-soon, coverage, recruit, stagger
  * BillingService      — subscribe, easy cancel, smart-retry downgrade, deposit
  * NotificationService — reminder scheduling, outbox dispatch, pluggable sink
  * WeightedScorer      — opt-in matching, same interface, reliability balance
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from orbit.domain.enums import (
    EventType,
    NotificationStatus,
    RsvpStatus,
    SubscriptionStatus,
    SubscriptionTier,
    VolunteerType,
)
from orbit.matching import (
    MemberSnapshot,
    RotationEngine,
    RotationInput,
    WeightedScorer,
)
from orbit.services.big_event_service import BigEventService
from orbit.services.billing_service import BillingService, MAX_RETRIES, PLUS_PRICE_CENTS
from orbit.services.club_service import ClubService
from orbit.services.notification_service import NotificationService
from orbit.services.repository import InMemoryRepository
from orbit.services.volunteer_service import VolunteerService
from orbit.domain.models import Venue


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.clubs = ClubService(self.repo)
        self.club = self.clubs.create_club("V1 Club", "City", min_density=6)

    def members(self, n, score=100):
        out = []
        for i in range(n):
            m = self.clubs.register_member(self.club.id, f"M{i}", f"m{i}@x.io")
            m.reliability_score = score
            out.append(m)
        return out


# --------------------------------------------------------------------------- #
# 1. Big events
# --------------------------------------------------------------------------- #
class TestBigEvent(Base):
    def setUp(self):
        super().setUp()
        self.svc = BigEventService(self.repo)
        self.repo.add_venue(Venue(club_id=self.club.id, name="Hall",
                                  partner=True, vetted=True))

    def test_create_uses_partner_venue_and_is_big(self):
        ev = self.svc.create_big_event(self.club.id, datetime(2026, 2, 1, 19),
                                       host_id="h1", backup_host_id="h2")
        self.assertEqual(ev.type, EventType.BIG)
        self.assertEqual(ev.club_id, self.club.id)
        self.assertEqual(ev.group_id, "")
        self.assertIsNotNone(ev.venue_id)  # partner venue auto-resolved
        self.assertEqual(self.svc.effective_host(ev.id), "h1")

    def test_backup_host_covers_when_no_primary(self):
        ev = self.svc.create_big_event(self.club.id, datetime(2026, 2, 1, 19),
                                       host_id=None, backup_host_id="backup")
        self.assertEqual(self.svc.effective_host(ev.id), "backup")

    def test_capacity_waitlists_and_promotes(self):
        ev = self.svc.create_big_event(self.club.id, datetime(2026, 2, 1, 19),
                                       capacity=2)
        r1 = self.svc.rsvp(ev.id, "a")
        r2 = self.svc.rsvp(ev.id, "b")
        r3 = self.svc.rsvp(ev.id, "c")
        self.assertEqual(r1.status, RsvpStatus.GOING)
        self.assertEqual(r2.status, RsvpStatus.GOING)
        self.assertEqual(r3.status, RsvpStatus.WAITLIST)

        summary = self.svc.attendance_summary(ev.id)
        self.assertEqual(summary["going"], 2)
        self.assertEqual(summary["waitlist"], 1)
        self.assertEqual(summary["spots_left"], 0)

        # a cancels -> c is promoted
        self.svc.cancel_rsvp(ev.id, "a")
        self.assertEqual(r3.status, RsvpStatus.GOING)

    def test_unlimited_capacity_never_waitlists(self):
        ev = self.svc.create_big_event(self.club.id, datetime(2026, 2, 1, 19))
        for name in "abcdef":
            r = self.svc.rsvp(ev.id, name)
            self.assertEqual(r.status, RsvpStatus.GOING)
        self.assertIsNone(self.svc.attendance_summary(ev.id)["spots_left"])


# --------------------------------------------------------------------------- #
# 2. Volunteers
# --------------------------------------------------------------------------- #
class TestVolunteer(Base):
    def setUp(self):
        super().setUp()
        self.svc = VolunteerService(self.repo)
        self.ppl = self.members(4)

    def test_assign_and_active(self):
        start = date(2026, 1, 1)
        role = self.svc.assign_role(self.club.id, self.ppl[0].id,
                                    VolunteerType.WELCOMER, start, term_days=90)
        self.assertEqual((role.term_end - role.term_start).days, 90)
        self.assertEqual(len(self.svc.active_roles(self.club.id, date(2026, 2, 1))), 1)
        self.assertEqual(len(self.svc.active_roles(self.club.id, date(2027, 1, 1))), 0)

    def test_expiring_soon(self):
        start = date(2026, 1, 1)
        self.svc.assign_role(self.club.id, self.ppl[0].id,
                             VolunteerType.WELCOMER, start, term_days=90)
        # term_end = 2026-04-01; on 2026-03-25 it's within 14 days.
        soon = self.svc.expiring_soon(self.club.id, date(2026, 3, 25), within_days=14)
        self.assertEqual(len(soon), 1)
        # a month earlier it is not expiring soon.
        self.assertEqual(
            len(self.svc.expiring_soon(self.club.id, date(2026, 2, 1))), 0
        )

    def test_coverage_all_four_types(self):
        cov = self.svc.coverage(self.club.id, date(2026, 2, 1))
        self.assertEqual(set(cov.keys()),
                         {t.value for t in VolunteerType})
        self.assertTrue(all(v == 0 for v in cov.values()))

    def test_recruit_replacement_picks_free_reliable_member(self):
        start = date(2026, 1, 1)
        # ppl[0] already holds a role; recruit should pick someone else.
        self.svc.assign_role(self.club.id, self.ppl[0].id,
                             VolunteerType.WELCOMER, start)
        self.ppl[1].reliability_score = 99  # most reliable free member
        got = self.svc.recruit_replacement(self.club.id,
                                           VolunteerType.HEALTH_WATCHER,
                                           date(2026, 1, 2))
        self.assertIsNotNone(got)
        self.assertNotEqual(got.member_id, self.ppl[0].id)

    def test_suggest_staggered_start_after_incumbent(self):
        start = date(2026, 1, 1)
        role = self.svc.assign_role(self.club.id, self.ppl[0].id,
                                    VolunteerType.WELCOMER, start, term_days=90)
        s = self.svc.suggest_staggered_start(self.club.id,
                                             VolunteerType.WELCOMER,
                                             date(2026, 2, 1))
        self.assertEqual(s, role.term_end + timedelta(days=1))


# --------------------------------------------------------------------------- #
# 3. Billing
# --------------------------------------------------------------------------- #
class TestBilling(Base):
    def setUp(self):
        super().setUp()
        self.me = self.members(1)[0].id

    def test_free_by_default(self):
        svc = BillingService(self.repo)
        sub = svc.get_or_create_subscription(self.me)
        self.assertEqual(sub.tier, SubscriptionTier.FREE)

    def test_subscribe_plus_success(self):
        svc = BillingService(self.repo)  # default gateway succeeds
        res = svc.subscribe_plus(self.me)
        self.assertTrue(res["ok"])
        self.assertEqual(res["subscription"].tier, SubscriptionTier.PLUS)
        self.assertEqual(res["subscription"].price_cents, PLUS_PRICE_CENTS)
        self.assertIsNotNone(res["subscription"].renews_at)

    def test_subscribe_plus_failure_marks_past_due(self):
        svc = BillingService(self.repo, gateway=lambda amt: False)
        res = svc.subscribe_plus(self.me)
        self.assertFalse(res["ok"])
        self.assertEqual(res["subscription"].status, SubscriptionStatus.PAST_DUE)
        self.assertEqual(res["subscription"].tier, SubscriptionTier.FREE)

    def test_easy_cancel_keeps_benefits_until_renewal(self):
        svc = BillingService(self.repo)
        svc.subscribe_plus(self.me)
        sub = svc.cancel(self.me)
        self.assertTrue(sub.cancel_at_period_end)
        self.assertEqual(sub.tier, SubscriptionTier.PLUS)  # still Plus for now
        # at renewal it downgrades cleanly, no charge
        res = svc.process_renewal(self.me)
        self.assertTrue(res["cancelled"])
        self.assertEqual(sub.tier, SubscriptionTier.FREE)

    def test_smart_retry_then_downgrade(self):
        # gateway fails always -> retries then downgrades after MAX_RETRIES
        svc = BillingService(self.repo, gateway=lambda amt: True)
        svc.subscribe_plus(self.me)  # succeeds (gateway ok)
        # now switch to a failing gateway for renewals
        svc.gateway = lambda amt: False
        downgraded = False
        for _ in range(MAX_RETRIES):
            res = svc.process_renewal(self.me)
            downgraded = res.get("downgraded", False)
        self.assertTrue(downgraded)
        sub = self.repo.subscription_for_member(self.me)
        self.assertEqual(sub.tier, SubscriptionTier.FREE)
        self.assertEqual(sub.status, SubscriptionStatus.CANCELLED)

    def test_deposit_and_refund(self):
        svc = BillingService(self.repo)
        p = svc.charge_event_deposit(self.me, "ev1", 2000)
        self.assertEqual(p.status.value, "succeeded")
        refunded = svc.refund_deposit(p.id)
        self.assertEqual(refunded.refunded_cents, 2000)
        self.assertEqual(refunded.status.value, "refunded")


# --------------------------------------------------------------------------- #
# 4. Notifications
# --------------------------------------------------------------------------- #
class TestNotifications(Base):
    def test_schedule_event_reminders_three_offsets(self):
        svc = NotificationService(self.repo)
        # create a minimal event in the repo
        from orbit.domain.models import Event
        ev = Event(group_id="g", starts_at=datetime(2026, 2, 10, 18, 0))
        self.repo.add_event(ev)
        notes = svc.schedule_event_reminders(ev.id, ["m1", "m2"])
        self.assertEqual(len(notes), 6)  # 3 offsets x 2 members
        # all start SCHEDULED
        self.assertTrue(all(n.status == NotificationStatus.SCHEDULED for n in notes))

    def test_dispatch_due_sends_past_notifications(self):
        svc = NotificationService(self.repo)
        past = datetime.utcnow() - timedelta(hours=1)
        future = datetime.utcnow() + timedelta(days=5)
        svc.schedule("m1", "x", "due now", past)
        svc.schedule("m1", "x", "later", future)
        result = svc.dispatch_due()
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["failed"], 0)
        # the future one is still pending
        self.assertEqual(len(svc.pending_for_member("m1")), 1)

    def test_failing_sink_marks_failed(self):
        svc = NotificationService(self.repo, sink=lambda n: False)
        svc.schedule("m1", "x", "body", datetime.utcnow() - timedelta(minutes=1))
        result = svc.dispatch_due()
        self.assertEqual(result["failed"], 1)

    def test_cancel_scheduled(self):
        svc = NotificationService(self.repo)
        n = svc.schedule("m1", "x", "body", datetime.utcnow() + timedelta(days=1))
        svc.cancel_scheduled(n.id)
        self.assertEqual(n.status, NotificationStatus.CANCELLED)
        self.assertEqual(len(svc.pending_for_member("m1")), 0)


# --------------------------------------------------------------------------- #
# 5. Weighted V1 matching
# --------------------------------------------------------------------------- #
class TestWeightedScorer(unittest.TestCase):
    def _members(self, n, score=100):
        return [
            MemberSnapshot(member_id=f"m{i}",
                           availability=frozenset({"tue_pm"}),
                           reliability_score=score)
            for i in range(n)
        ]

    def test_weighted_engine_same_interface_produces_valid_groups(self):
        engine = RotationEngine(scorer=WeightedScorer())
        proposal = engine.generate(RotationInput(members=self._members(6)))
        self.assertEqual(len(proposal.groups), 1)
        self.assertEqual(proposal.groups[0].size, 6)

    def test_weighted_respects_blocks(self):
        engine = RotationEngine(scorer=WeightedScorer())
        members = self._members(8)
        blocks = {"m0": {"m1"}, "m1": {"m0"}}
        proposal = engine.generate(RotationInput(members=members, blocks=blocks))
        for g in proposal.groups:
            self.assertFalse("m0" in g.member_ids and "m1" in g.member_ids)

    def test_weighted_still_deterministic(self):
        engine = RotationEngine(scorer=WeightedScorer())
        members = self._members(12)
        p1 = engine.generate(RotationInput(members=members, seed=5))
        p2 = engine.generate(RotationInput(members=members, seed=5))
        self.assertEqual([sorted(g.member_ids) for g in p1.groups],
                         [sorted(g.member_ids) for g in p2.groups])

    def test_default_engine_unchanged_without_scorer(self):
        # No scorer -> MVP path still works (regression guard).
        engine = RotationEngine()
        proposal = engine.generate(RotationInput(members=self._members(6)))
        self.assertEqual(len(proposal.groups), 1)


# --------------------------------------------------------------------------- #
# 6. Persistence of V1 entities (JSON round-trip)
# --------------------------------------------------------------------------- #
class TestV1Persistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "v1.json")

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def test_v1_entities_survive_reload(self):
        from orbit.services.json_repository import JsonFileRepository
        from orbit.services.club_service import ClubService
        from orbit.services.big_event_service import BigEventService
        from orbit.services.billing_service import BillingService
        from orbit.services.volunteer_service import VolunteerService
        from orbit.services.notification_service import NotificationService

        repo = JsonFileRepository(self.path)
        clubs = ClubService(repo)
        club = clubs.create_club("P", "City", min_density=2)
        m = clubs.register_member(club.id, "A", "a@x.io")

        # big event with capacity + backup host
        big = BigEventService(repo)
        ev = big.create_big_event(club.id, datetime(2026, 3, 1, 19),
                                  host_id=m.id, backup_host_id=None, capacity=5)
        # billing: subscribe + a payment
        billing = BillingService(repo)
        billing.subscribe_plus(m.id)
        # volunteer role
        vol = VolunteerService(repo)
        vol.assign_role(club.id, m.id, VolunteerType.WELCOMER, date(2026, 1, 1))
        # notification
        notif = NotificationService(repo)
        notif.schedule(m.id, "x", "hi", datetime(2026, 3, 1, 12, 0))
        repo.save()

        # Reload into a fresh repo and verify everything persisted.
        repo2 = JsonFileRepository(self.path)
        self.assertEqual(len(repo2.subscriptions), 1)
        self.assertEqual(len(repo2.payments), 1)
        self.assertEqual(len(repo2.volunteer_roles), 1)
        self.assertEqual(len(repo2.notifications), 1)
        ev2 = repo2.events[ev.id]
        self.assertEqual(ev2.type, EventType.BIG)
        self.assertEqual(ev2.capacity, 5)
        self.assertEqual(ev2.club_id, club.id)
        sub2 = repo2.subscription_for_member(m.id)
        self.assertEqual(sub2.tier, SubscriptionTier.PLUS)


if __name__ == "__main__":
    unittest.main()
