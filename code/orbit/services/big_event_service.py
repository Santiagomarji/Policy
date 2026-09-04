"""
Orbit — Rotating Social Club
Service: BigEventService.

Handles the monthly club-wide "big" gathering flow:

  * creating the club-wide big event (with a host + backup-host safety net),
  * RSVP with capacity-aware overflow to a waitlist,
  * automatic promotion off the waitlist when a seat frees up,
  * cancellation (which frees a seat and promotes the next in line),
  * resolving the effective host, and a lightweight attendance summary.

Unlike a group's biweekly small event, a big event spans the whole club:
its ``group_id`` is empty and its ``club_id`` is set. A partner venue backs
it automatically when one exists, and ``backup_owner_id`` covers the case
where the primary host drops (FR-23-style safety net for big gatherings).

Pure standard library. Depends only on the in-memory repository so it is
runnable and testable without a database. In production the repository is
swapped for the PostgreSQL-backed implementation behind the same method
names (see docs/07_Database_Design.md).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..domain.models import Event, Rsvp
from ..domain.enums import EventStatus, EventType, RsvpStatus
from ..services.repository import InMemoryRepository


class BigEventService:
    """Run the monthly club-wide big gathering.

    A big event is club-scoped rather than group-scoped: every member of the
    club may attend. Because turnout can exceed the venue's capacity, RSVPs
    that arrive after the cap is reached are placed on a waitlist and are
    promoted to ``GOING`` automatically as seats free up.
    """

    def __init__(self, repo: InMemoryRepository) -> None:
        """Bind the service to a repository instance.

        Args:
            repo: The storage layer used to look up and persist entities.
        """
        self.repo = repo

    # --- event creation ------------------------------------------------- #
    def create_big_event(
        self,
        club_id: str,
        starts_at: datetime,
        host_id: Optional[str] = None,
        backup_host_id: Optional[str] = None,
        venue_id: Optional[str] = None,
        capacity: Optional[int] = None,
    ) -> Event:
        """Create the monthly club-wide big event.

        The event spans all groups in the club, so ``group_id`` is left empty
        and ``club_id`` is set instead. A primary host and an optional backup
        host provide a safety net (see :meth:`effective_host`). If no explicit
        venue is given, the club's partner venue is used when one exists.

        Args:
            club_id: Id of the club hosting the gathering.
            starts_at: When the event starts.
            host_id: Optional id of the primary host (event owner).
            backup_host_id: Optional id of the backup/co-host.
            venue_id: Optional explicit venue id. When ``None``, the club's
                partner venue is used if one is configured.
            capacity: Optional attendance cap. ``None`` means unlimited; any
                positive value triggers waitlisting once the cap is reached.

        Returns:
            The persisted, ``PUBLISHED`` big :class:`Event`.
        """
        partner = self.repo.partner_venue(club_id)
        resolved_venue_id = venue_id or (partner.id if partner else None)

        event = Event(
            group_id="",  # big events span all groups; no single group.
            starts_at=starts_at,
            type=EventType.BIG,
            venue_id=resolved_venue_id,
            owner_id=host_id,
            backup_owner_id=backup_host_id,
            club_id=club_id,
            capacity=capacity,
            status=EventStatus.PUBLISHED,
            is_fallback=False,
        )
        return self.repo.add_event(event)

    # --- rsvp / waitlist ------------------------------------------------ #
    def rsvp(self, event_id: str, member_id: str) -> Rsvp:
        """Record a member's RSVP, waitlisting once capacity is reached.

        Counts the current ``GOING`` RSVPs for the event. If the event has a
        capacity and it is already full, the member is placed on the waitlist;
        otherwise they are marked ``GOING``. To keep the flow simple, no
        de-duplication is performed: a repeat RSVP is still recorded.

        Args:
            event_id: Id of the big event being responded to.
            member_id: Id of the responding member.

        Returns:
            The persisted :class:`Rsvp` (``GOING`` or ``WAITLIST``).
        """
        event = self.repo.events[event_id]

        going_count = sum(
            1
            for r in self.repo.rsvps_for_event(event_id)
            if r.status == RsvpStatus.GOING
        )

        if event.capacity is not None and going_count >= event.capacity:
            status = RsvpStatus.WAITLIST
        else:
            status = RsvpStatus.GOING

        rsvp = Rsvp(event_id=event_id, member_id=member_id, status=status)
        return self.repo.add_rsvp(rsvp)

    def promote_from_waitlist(self, event_id: str) -> Optional[str]:
        """Promote the first waitlisted member if a seat is free.

        A seat is free when the event has a capacity and the current ``GOING``
        count is below it. The first ``WAITLIST`` RSVP found is flipped to
        ``GOING`` in place (the in-memory repository returns live objects).

        Args:
            event_id: Id of the big event.

        Returns:
            The promoted member's id, or ``None`` if there was no free seat or
            no one on the waitlist.
        """
        event = self.repo.events[event_id]
        if event.capacity is None:
            return None

        rsvps = self.repo.rsvps_for_event(event_id)
        going_count = sum(1 for r in rsvps if r.status == RsvpStatus.GOING)

        if going_count >= event.capacity:
            return None

        for rsvp in rsvps:
            if rsvp.status == RsvpStatus.WAITLIST:
                rsvp.status = RsvpStatus.GOING
                return rsvp.member_id

        return None

    def cancel_rsvp(self, event_id: str, member_id: str) -> None:
        """Cancel a member's RSVP and backfill the freed seat.

        The member's RSVP is set to ``DECLINED``; then
        :meth:`promote_from_waitlist` runs so the next waitlisted member (if
        any) takes the seat that just opened up. If the member has no RSVP for
        this event, this is a no-op aside from the promotion attempt.

        Args:
            event_id: Id of the big event.
            member_id: Id of the member cancelling.
        """
        for rsvp in self.repo.rsvps_for_event(event_id):
            if rsvp.member_id == member_id:
                rsvp.status = RsvpStatus.DECLINED
                break

        self.promote_from_waitlist(event_id)

    # --- hosting / summary ---------------------------------------------- #
    def effective_host(self, event_id: str) -> Optional[str]:
        """Resolve who is actually hosting the event.

        The primary host owns the event; if none is set, the backup host
        covers. This is the safety net: if the host drops, the backup keeps
        the gathering from going dark.

        Args:
            event_id: Id of the big event.

        Returns:
            The primary host id if set, else the backup host id, else ``None``.
        """
        event = self.repo.events[event_id]
        return event.owner_id or event.backup_owner_id or None

    def attendance_summary(self, event_id: str) -> dict:
        """Summarize current attendance for the event.

        Args:
            event_id: Id of the big event.

        Returns:
            A dict with:
              * ``going``: number of ``GOING`` RSVPs,
              * ``waitlist``: number of ``WAITLIST`` RSVPs,
              * ``capacity``: the event capacity (``None`` if unlimited),
              * ``spots_left``: ``capacity - going`` when capacity is set,
                otherwise ``None`` (unlimited).
        """
        event = self.repo.events[event_id]
        rsvps = self.repo.rsvps_for_event(event_id)

        going = sum(1 for r in rsvps if r.status == RsvpStatus.GOING)
        waitlist = sum(1 for r in rsvps if r.status == RsvpStatus.WAITLIST)
        capacity = event.capacity

        return {
            "going": going,
            "waitlist": waitlist,
            "capacity": capacity,
            "spots_left": (capacity - going) if capacity is not None else None,
        }
