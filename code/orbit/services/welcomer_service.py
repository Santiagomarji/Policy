"""
Orbit — Welcomer onboarding flow.

Plugs the #1 retention leak from the research (doc 01): new members who are
never welcomed quietly disappear. When someone joins, this service:

  1. finds the club's active **Welcomer** volunteer (if any) and records that
     they should reach out,
  2. picks a **first-event buddy** — a reliable existing member who will look
     out for the newcomer at their first event,
  3. schedules friendly **welcome notifications** to the newcomer, the buddy,
     and the welcomer (via the outbox NotificationService).

It is deliberately tolerant: if there is no welcomer or no candidate buddy yet
(e.g. a brand-new club), it still welcomes the member and returns what it could
do — onboarding never hard-fails.

Pure standard library. Reads/writes through the shared repository interface.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from ..domain.enums import MemberStatus, VolunteerType
from ..domain.models import Member
from .notification_service import NotificationService
from .volunteer_service import VolunteerService


class WelcomerService:
    """Onboard a new member: welcomer + first-event buddy + welcome messages."""

    def __init__(
        self,
        repo,
        notifications: Optional[NotificationService] = None,
        volunteers: Optional[VolunteerService] = None,
    ) -> None:
        """Bind to a repository and (optionally) share notification/volunteer services.

        Args:
            repo: The store holding members, volunteer roles, notifications.
            notifications: NotificationService to schedule welcome messages.
                Created on ``repo`` if not provided.
            volunteers: VolunteerService to find the active welcomer. Created
                on ``repo`` if not provided.
        """
        self.repo = repo
        self.notifications = notifications or NotificationService(repo)
        self.volunteers = volunteers or VolunteerService(repo)

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def onboard(
        self,
        member_id: str,
        on_date: Optional[date] = None,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Run the welcome flow for a newly registered member.

        Args:
            member_id: The new member to onboard.
            on_date: Date used to find the active welcomer (default today).
            now: Timestamp for the welcome notifications (default utcnow).

        Returns:
            A summary dict:
              ``{"member_id", "welcomer_id", "buddy_id",
                 "notifications": int}``
            with ``welcomer_id`` / ``buddy_id`` possibly ``None`` when the club
            has no welcomer or no eligible buddy yet.

        Raises:
            KeyError: If ``member_id`` is unknown.
        """
        member = self.repo.members[member_id]
        on_date = on_date or date.today()
        now = now or datetime.utcnow()

        welcomer_id = self._find_welcomer(member.club_id, member_id, on_date)
        buddy_id = self._pick_buddy(member.club_id, member_id)

        notes = self._send_welcome(member, welcomer_id, buddy_id, now)

        return {
            "member_id": member_id,
            "welcomer_id": welcomer_id,
            "buddy_id": buddy_id,
            "notifications": len(notes),
        }

    def needs_welcome(self, club_id: str) -> list[Member]:
        """Members who joined but have no group yet (the at-risk newcomers).

        Useful for a Welcomer dashboard: everyone active in the club who is not
        yet placed in the latest committed cycle's groups.
        """
        placed: set[str] = set()
        cycle = self.repo.latest_committed_cycle(club_id)
        if cycle is not None:
            for g in self.repo.groups_for_cycle(cycle.id):
                placed.update(g.member_ids)
        return [
            m
            for m in self.repo.members_for_club(club_id)
            if m.status == MemberStatus.ACTIVE and m.id not in placed
        ]

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _find_welcomer(
        self, club_id: str, new_member_id: str, on_date: date
    ) -> Optional[str]:
        """Return the member_id of an active Welcomer, if one exists.

        Never returns the newcomer themselves.
        """
        for role in self.volunteers.active_roles(club_id, on_date):
            if role.type == VolunteerType.WELCOMER and role.member_id != new_member_id:
                return role.member_id
        return None

    def _pick_buddy(self, club_id: str, new_member_id: str) -> Optional[str]:
        """Pick a reliable existing member to buddy the newcomer.

        Chooses the most reliable active member (excluding the newcomer),
        deterministic by name on ties. Returns ``None`` if the newcomer is the
        only member so far.
        """
        candidates = [
            m
            for m in self.repo.members_for_club(club_id)
            if m.status == MemberStatus.ACTIVE and m.id != new_member_id
        ]
        if not candidates:
            return None
        best = max(candidates, key=lambda m: (m.reliability_score, m.name))
        return best.id

    def _send_welcome(
        self,
        member: Member,
        welcomer_id: Optional[str],
        buddy_id: Optional[str],
        now: datetime,
    ) -> list:
        """Schedule welcome notifications; returns the created notifications."""
        created = []
        # To the newcomer.
        created.append(self.notifications.schedule(
            member_id=member.id,
            kind="welcome",
            body=f"Welcome to Orbit, {member.name}! "
                 "You'll be matched into a small group soon.",
            send_at=now,
        ))
        # To the buddy.
        if buddy_id is not None:
            created.append(self.notifications.schedule(
                member_id=buddy_id,
                kind="welcome_buddy",
                body=f"You're the first-event buddy for {member.name}. "
                     "Say hi and help them feel at home!",
                send_at=now,
            ))
        # To the welcomer.
        if welcomer_id is not None:
            created.append(self.notifications.schedule(
                member_id=welcomer_id,
                kind="welcome_assignment",
                body=f"New member {member.name} joined — please reach out and welcome them.",
                send_at=now,
            ))
        return created
