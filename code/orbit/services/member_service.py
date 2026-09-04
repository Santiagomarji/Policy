"""
Orbit — MemberService (the member-facing / customer experience layer).

The rest of the app is operator-facing. This service answers the questions a
*member* (the real customer) actually has:

  * "What group am I in right now?"          -> current_group
  * "What's my next event?"                  -> upcoming_event
  * "Who have I met across cycles?"          -> people_ive_met
  * "Let me RSVP to my next event."          -> (router uses upcoming_event + rsvp)
  * "Block / report someone."                -> block_member (safety)
  * "How am I doing?" (reliability/streak)   -> profile

Pure standard library. Reads through the shared repository interface, so it
works identically on the in-memory, JSON, or PostgreSQL backends.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..domain.enums import CycleStatus, EventStatus
from ..domain.models import Event, Group, Member
from .repository import InMemoryRepository


class MemberService:
    """Member-facing queries and self-service actions."""

    def __init__(self, repo: InMemoryRepository) -> None:
        self.repo = repo

    # ------------------------------------------------------------------ #
    # lookups
    # ------------------------------------------------------------------ #
    def get_member(self, member_id: str) -> Member:
        """Return a member or raise KeyError."""
        return self.repo.members[member_id]

    def current_group(self, member_id: str) -> Optional[Group]:
        """The member's group in the latest committed cycle, if any.

        This is the core "see my group" answer. Returns None if the member
        hasn't been placed yet (e.g. before the first rotation, or if they
        were unplaced this cycle).
        """
        member = self.repo.members[member_id]
        cycle = self.repo.latest_committed_cycle(member.club_id)
        if cycle is None:
            return None
        for g in self.repo.groups_for_cycle(cycle.id):
            if member_id in g.member_ids:
                return g
        return None

    def groupmates(self, member_id: str) -> list[Member]:
        """The other members of the caller's current group (hydrated)."""
        g = self.current_group(member_id)
        if g is None:
            return []
        out = []
        for mid in g.member_ids:
            if mid == member_id:
                continue
            m = self.repo.members.get(mid)
            if m is not None:
                out.append(m)
        return out

    def upcoming_event(self, member_id: str) -> Optional[Event]:
        """The member's next scheduled event (soonest future, not completed).

        Looks at the member's current group's events and returns the earliest
        one that is published/draft and starts in the future. Falls back to
        the soonest non-completed event if none are strictly in the future
        (so a member always sees "the next thing" even with clock skew).
        """
        g = self.current_group(member_id)
        if g is None:
            return None
        events = [
            e
            for e in self.repo.events_for_group(g.id)
            if e.status not in (EventStatus.COMPLETED, EventStatus.CANCELLED)
        ]
        if not events:
            return None
        now = datetime.utcnow()
        future = [e for e in events if e.starts_at >= now]
        pool = future if future else events
        return sorted(pool, key=lambda e: e.starts_at)[0]

    def people_ive_met(self, member_id: str) -> list[Member]:
        """Everyone the member has met across all cycles (anti-clique payoff).

        This is the emotional core of the product for the customer: the set of
        real connections they've accumulated. Reads the met-history the
        rotation engine maintains.
        """
        met_ids = self.repo.met_history.get(member_id, set())
        out = []
        for mid in sorted(met_ids):
            m = self.repo.members.get(mid)
            if m is not None:
                out.append(m)
        return out

    def profile(self, member_id: str) -> dict[str, Any]:
        """A compact 'how am I doing' summary for the member."""
        m = self.repo.members[member_id]
        g = self.current_group(member_id)
        upcoming = self.upcoming_event(member_id)
        return {
            "id": m.id,
            "name": m.name,
            "reliability_score": m.reliability_score,
            "current_streak": m.current_streak,
            "people_met": len(self.repo.met_history.get(member_id, set())),
            "current_group_id": g.id if g else None,
            "current_group_name": g.name if g else None,
            "has_upcoming_event": upcoming is not None,
        }

    # ------------------------------------------------------------------ #
    # self-service safety
    # ------------------------------------------------------------------ #
    def block_member(self, member_id: str, other_id: str) -> None:
        """Member blocks another member (symmetric, enforced by matching).

        Raises ValueError if a member tries to block themselves, or KeyError
        if either member is unknown.
        """
        if member_id == other_id:
            raise ValueError("cannot block yourself")
        if member_id not in self.repo.members:
            raise KeyError(member_id)
        if other_id not in self.repo.members:
            raise KeyError(other_id)
        self.repo.add_block(member_id, other_id)
