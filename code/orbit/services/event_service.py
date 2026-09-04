"""
Orbit — Rotating Social Club
Service: EventService.

Handles the event lifecycle for a group:

  * event creation (owner-run and auto-run fallback),
  * ownership rotation with fallback (FR-23),
  * RSVP and attendance recording.

Pure standard library. Depends only on the in-memory repository so it is
runnable and testable without a database. In production the repository is
swapped for the PostgreSQL-backed implementation behind the same method
names (see docs/07_Database_Design.md).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..domain.models import Event, EventType, Rsvp
from ..domain.enums import EventStatus, RsvpStatus
from ..services.repository import InMemoryRepository


class EventService:
    """Create events, rotate ownership, and record attendance.

    Every group runs a small biweekly event each cycle. Ideally a group
    member owns (hosts) it. When no member will take ownership, the club
    auto-runs a fallback event at a partner venue so the group never goes
    dark (FR-23).
    """

    def __init__(self, repo: InMemoryRepository) -> None:
        """Bind the service to a repository instance.

        Args:
            repo: The storage layer used to look up and persist entities.
        """
        self.repo = repo

    # --- event creation ------------------------------------------------- #
    def create_event_for_group(
        self,
        group_id: str,
        starts_at: datetime,
        venue_id: Optional[str] = None,
    ) -> Event:
        """Create the group's biweekly small event.

        The current group owner hosts the event. If the group has no owner
        assigned for this cycle, the club auto-runs a fallback event instead
        (see :meth:`create_fallback_event`).

        Args:
            group_id: Id of the group the event belongs to.
            starts_at: When the event starts.
            venue_id: Optional venue id; ``None`` if not yet chosen.

        Returns:
            The persisted :class:`Event`. When the group has no owner this is
            the fallback event created by :meth:`create_fallback_event`.
        """
        group = self.repo.groups[group_id]

        # No owner for this cycle -> the club steps in with a fallback event.
        if not group.owner_id:
            return self.create_fallback_event(group_id, starts_at)

        event = Event(
            group_id=group_id,
            starts_at=starts_at,
            type=EventType.SMALL,
            venue_id=venue_id,
            owner_id=group.owner_id,
            status=EventStatus.PUBLISHED,
            is_fallback=False,
        )
        return self.repo.add_event(event)

    def create_fallback_event(
        self,
        group_id: str,
        starts_at: datetime,
    ) -> Event:
        """Create an auto-run fallback event at a partner venue.

        Used when no group member will host. The event has no owner and is
        placed at a club partner venue when one is available; otherwise the
        venue is left unset for later assignment (FR-23).

        Args:
            group_id: Id of the group the event belongs to.
            starts_at: When the event starts.

        Returns:
            The persisted fallback :class:`Event`.
        """
        group = self.repo.groups[group_id]
        partner = self.repo.partner_venue(group.club_id)

        event = Event(
            group_id=group_id,
            starts_at=starts_at,
            type=EventType.SMALL,
            venue_id=partner.id if partner else None,
            owner_id=None,
            status=EventStatus.PUBLISHED,
            is_fallback=True,
        )
        return self.repo.add_event(event)

    # --- rsvp / attendance --------------------------------------------- #
    def rsvp(
        self,
        event_id: str,
        member_id: str,
        status: RsvpStatus = RsvpStatus.GOING,
    ) -> Rsvp:
        """Record a member's RSVP to an event.

        Args:
            event_id: Id of the event being responded to.
            member_id: Id of the responding member.
            status: The RSVP status; defaults to ``GOING``.

        Returns:
            The persisted :class:`Rsvp`.
        """
        rsvp = Rsvp(event_id=event_id, member_id=member_id, status=status)
        return self.repo.add_rsvp(rsvp)

    def record_attendance(
        self,
        event_id: str,
        attended_ids: list[str],
        no_show_ids: list[str],
    ) -> None:
        """Record attendance outcomes and close out the event.

        Marks ``attended=True`` for members who showed up and sets the RSVP
        status to ``NO_SHOW`` for members who did not. The event is then
        moved to ``COMPLETED``. Ids not present as RSVPs are ignored.

        Args:
            event_id: Id of the event to finalize.
            attended_ids: Member ids who attended.
            no_show_ids: Member ids who RSVP'd but did not attend.
        """
        attended = set(attended_ids)
        no_shows = set(no_show_ids)

        for rsvp in self.repo.rsvps_for_event(event_id):
            if rsvp.member_id in attended:
                rsvp.attended = True
            if rsvp.member_id in no_shows:
                rsvp.status = RsvpStatus.NO_SHOW

        event = self.repo.events[event_id]
        event.status = EventStatus.COMPLETED

    # --- ownership rotation -------------------------------------------- #
    def offer_ownership(
        self,
        group_id: str,
        candidate_ids: list[str],
    ) -> Optional[str]:
        """Offer group ownership to candidates in order until one accepts.

        Acceptance is simulated by a reliability gate: the first candidate
        with ``reliability_score >= 50`` accepts and becomes the group owner
        for this cycle. If no candidate accepts, ownership is left unset and
        the caller should fall back to :meth:`create_fallback_event`.

        Args:
            group_id: Id of the group needing an owner.
            candidate_ids: Ordered list of member ids to offer ownership to.

        Returns:
            The accepting member's id, or ``None`` if nobody accepted.
        """
        group = self.repo.groups[group_id]

        for member_id in candidate_ids:
            member = self.repo.members.get(member_id)
            if member is None:
                continue
            if member.reliability_score >= 50:
                group.owner_id = member.id
                return member.id

        return None
