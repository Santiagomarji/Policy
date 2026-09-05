"""
Orbit — in-memory repository.

A tiny storage layer so the services are runnable and testable without a
database. In production this is replaced by the PostgreSQL schema in
docs/07_Database_Design.md (same entities), behind the same method names.
"""
from __future__ import annotations

from typing import Optional

from ..domain.models import (
    Club,
    Cycle,
    Event,
    Group,
    Member,
    Notification,
    Payment,
    Rating,
    Rsvp,
    Subscription,
    Venue,
    VolunteerRole,
)


class InMemoryRepository:
    """Dict-backed store keyed by entity id."""

    def __init__(self) -> None:
        self.clubs: dict[str, Club] = {}
        self.members: dict[str, Member] = {}
        self.cycles: dict[str, Cycle] = {}
        self.groups: dict[str, Group] = {}
        self.events: dict[str, Event] = {}
        self.rsvps: dict[str, Rsvp] = {}
        self.venues: dict[str, Venue] = {}
        self.ratings: dict[str, Rating] = {}
        self.volunteer_roles: dict[str, VolunteerRole] = {}
        self.subscriptions: dict[str, Subscription] = {}
        self.payments: dict[str, Payment] = {}
        self.notifications: dict[str, Notification] = {}
        # member_id -> set of member_ids they have met (anti-clique history).
        self.met_history: dict[str, set[str]] = {}
        # member_id -> set of blocked member_ids (symmetric, safety).
        self.blocks: dict[str, set[str]] = {}

    # --- clubs ---------------------------------------------------------- #
    def add_club(self, club: Club) -> Club:
        self.clubs[club.id] = club
        return club

    # --- members -------------------------------------------------------- #
    def add_member(self, member: Member) -> Member:
        self.members[member.id] = member
        self.met_history.setdefault(member.id, set())
        return member

    def members_for_club(self, club_id: str) -> list[Member]:
        return [m for m in self.members.values() if m.club_id == club_id]

    # --- cycles --------------------------------------------------------- #
    def add_cycle(self, cycle: Cycle) -> Cycle:
        self.cycles[cycle.id] = cycle
        return cycle

    def latest_committed_cycle(self, club_id: str) -> Optional[Cycle]:
        from ..domain.enums import CycleStatus

        committed = [
            c
            for c in self.cycles.values()
            if c.club_id == club_id and c.status == CycleStatus.COMMITTED
        ]
        if not committed:
            return None
        return sorted(committed, key=lambda c: c.start_date)[-1]

    # --- groups --------------------------------------------------------- #
    def add_group(self, group: Group) -> Group:
        self.groups[group.id] = group
        return group

    def groups_for_cycle(self, cycle_id: str) -> list[Group]:
        return [g for g in self.groups.values() if g.cycle_id == cycle_id]

    # --- events / rsvps ------------------------------------------------- #
    def add_event(self, event: Event) -> Event:
        self.events[event.id] = event
        return event

    def add_rsvp(self, rsvp: Rsvp) -> Rsvp:
        self.rsvps[rsvp.id] = rsvp
        return rsvp

    def rsvps_for_event(self, event_id: str) -> list[Rsvp]:
        return [r for r in self.rsvps.values() if r.event_id == event_id]

    def events_for_group(self, group_id: str) -> list[Event]:
        return [e for e in self.events.values() if e.group_id == group_id]

    # --- ratings -------------------------------------------------------- #
    def add_rating(self, rating: Rating) -> Rating:
        self.ratings[rating.id] = rating
        return rating

    def ratings_for_event(self, event_id: str) -> list[Rating]:
        return [r for r in self.ratings.values() if r.event_id == event_id]

    # --- venues --------------------------------------------------------- #
    def add_venue(self, venue: Venue) -> Venue:
        self.venues[venue.id] = venue
        return venue

    def partner_venue(self, club_id: str) -> Optional[Venue]:
        for v in self.venues.values():
            if v.club_id == club_id and v.partner:
                return v
        return None

    # --- volunteer roles ------------------------------------------------ #
    def add_volunteer_role(self, role: VolunteerRole) -> VolunteerRole:
        self.volunteer_roles[role.id] = role
        return role

    def volunteer_roles_for_club(self, club_id: str) -> list[VolunteerRole]:
        return [r for r in self.volunteer_roles.values() if r.club_id == club_id]

    # --- subscriptions -------------------------------------------------- #
    def add_subscription(self, sub: Subscription) -> Subscription:
        self.subscriptions[sub.id] = sub
        return sub

    def subscription_for_member(self, member_id: str) -> Optional[Subscription]:
        for s in self.subscriptions.values():
            if s.member_id == member_id:
                return s
        return None

    # --- payments ------------------------------------------------------- #
    def add_payment(self, payment: Payment) -> Payment:
        self.payments[payment.id] = payment
        return payment

    def payments_for_member(self, member_id: str) -> list[Payment]:
        return [p for p in self.payments.values() if p.member_id == member_id]

    # --- notifications (outbox) ----------------------------------------- #
    def add_notification(self, n: Notification) -> Notification:
        self.notifications[n.id] = n
        return n

    def notifications_for_member(self, member_id: str) -> list[Notification]:
        return [n for n in self.notifications.values() if n.member_id == member_id]

    def due_notifications(self, now) -> list[Notification]:
        """Scheduled notifications whose send_at has passed."""
        from ..domain.enums import NotificationStatus
        return [
            n for n in self.notifications.values()
            if n.status == NotificationStatus.SCHEDULED and n.send_at <= now
        ]

    # --- history / safety ---------------------------------------------- #
    def record_met(self, member_ids: list[str]) -> None:
        """Record that everyone in member_ids has now met each other."""
        for a in member_ids:
            for b in member_ids:
                if a != b:
                    self.met_history.setdefault(a, set()).add(b)

    def add_block(self, a: str, b: str) -> None:
        """Add a symmetric block between two members."""
        self.blocks.setdefault(a, set()).add(b)
        self.blocks.setdefault(b, set()).add(a)
