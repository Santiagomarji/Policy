"""
Orbit — Volunteer service.

Manages term-limited, staggered volunteer roles with proactive replacement
recruiting (see doc 03 sustainability; FR-52/FR-53).

Every club is powered by a handful of volunteer roles (big-event host,
welcomer, health watcher, rotation steward). To keep the club sustainable we
avoid two failure modes:

* **Burnout** — roles are *term-limited*, so no one is on the hook forever.
* **Coverage cliffs** — terms are *staggered* and replacements are recruited
  *before* the incumbent's term ends, so there is a handover window rather
  than a hard cutover.

Pure standard library. Operates on ``VolunteerRole`` and ``Member`` records
held by the repository (same method names as the production data layer).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from ..domain.enums import VolunteerType
from ..domain.models import VolunteerRole


class VolunteerService:
    """Assign, track, and proactively backfill term-limited volunteer roles.

    The service is deliberately stateless beyond its repository handle: all
    role data lives in the repo, so callers reading through the repo always
    see the roles this service creates.
    """

    def __init__(self, repo) -> None:
        """Bind the service to a repository.

        Args:
            repo: The store holding ``VolunteerRole`` and ``Member`` records.
                Must expose ``add_volunteer_role``,
                ``volunteer_roles_for_club``, ``members_for_club``, and a
                ``members`` dict.
        """
        self.repo = repo

    def assign_role(
        self,
        club_id: str,
        member_id: str,
        role_type: VolunteerType,
        term_start: date,
        term_days: int = 90,
    ) -> VolunteerRole:
        """Assign a member a volunteer role for a fixed term.

        The term runs from ``term_start`` for ``term_days`` days (inclusive of
        the start), giving a natural expiry that powers the term-limit
        mechanic.

        Args:
            club_id: Club the role belongs to.
            member_id: Member taking on the role.
            role_type: Which volunteer role is being filled.
            term_start: First day of the term.
            term_days: Length of the term in days (default 90).

        Returns:
            The persisted :class:`VolunteerRole`.
        """
        term_end = term_start + timedelta(days=term_days)
        role = VolunteerRole(
            member_id=member_id,
            club_id=club_id,
            type=role_type,
            term_start=term_start,
            term_end=term_end,
        )
        return self.repo.add_volunteer_role(role)

    def active_roles(self, club_id: str, on_date: date) -> list[VolunteerRole]:
        """Return the roles that are active on a given date.

        A role is active when ``term_start <= on_date <= term_end`` (both
        bounds inclusive).

        Args:
            club_id: Club to inspect.
            on_date: The date to evaluate activeness against.

        Returns:
            List of active :class:`VolunteerRole` objects (possibly empty).
        """
        return [
            r
            for r in self.repo.volunteer_roles_for_club(club_id)
            if r.term_start <= on_date <= r.term_end
        ]

    def expiring_soon(
        self,
        club_id: str,
        on_date: date,
        within_days: int = 14,
    ) -> list[VolunteerRole]:
        """Return active roles whose term ends within the coming window.

        This is the proactive-recruiting trigger: it surfaces roles about to
        lapse so a replacement can be recruited *before* the coverage cliff
        rather than after it.

        A role qualifies when it is active on ``on_date`` **and** its
        ``term_end`` falls in the closed interval
        ``[on_date, on_date + within_days]``.

        Args:
            club_id: Club to inspect.
            on_date: The reference date (typically "today").
            within_days: How far ahead to look for expiries (default 14).

        Returns:
            List of soon-to-expire active :class:`VolunteerRole` objects.
        """
        horizon = on_date + timedelta(days=within_days)
        return [
            r
            for r in self.active_roles(club_id, on_date)
            if on_date <= r.term_end <= horizon
        ]

    def coverage(self, club_id: str, on_date: date) -> dict:
        """Report how many active roles exist per volunteer type.

        Every :class:`VolunteerType` is present in the result, defaulting to
        ``0`` when uncovered, so callers can render a complete coverage board
        without special-casing missing keys.

        Args:
            club_id: Club to inspect.
            on_date: The date to evaluate coverage against.

        Returns:
            A dict mapping each ``VolunteerType.value`` to its active count,
            e.g. ``{"big_event_host": 1, "welcomer": 0, ...}``.
        """
        counts: dict = {vt.value: 0 for vt in VolunteerType}
        for role in self.active_roles(club_id, on_date):
            counts[role.type.value] += 1
        return counts

    def is_role_covered(
        self,
        club_id: str,
        role_type: VolunteerType,
        on_date: date,
    ) -> bool:
        """Return whether a role type has at least one active holder.

        Args:
            club_id: Club to inspect.
            role_type: The volunteer role to check.
            on_date: The date to evaluate coverage against.

        Returns:
            ``True`` if one or more active roles of ``role_type`` exist,
            otherwise ``False``.
        """
        return any(
            r.type == role_type for r in self.active_roles(club_id, on_date)
        )

    def recruit_replacement(
        self,
        club_id: str,
        role_type: VolunteerType,
        on_date: date,
        term_days: int = 90,
    ) -> Optional[VolunteerRole]:
        """Recruit the best available member into a role, starting today.

        Picks the most reliable **active, eligible** member of the club who
        does not already hold *any* active role on ``on_date`` (so we spread
        the load rather than piling roles on the same people), and assigns
        them ``role_type`` with ``term_start = on_date``.

        Because the new term starts on ``on_date`` — which differs from the
        incumbents' start dates — terms are naturally staggered, giving the
        overlap-then-handover behaviour that avoids coverage cliffs.

        Args:
            club_id: Club to recruit for.
            role_type: The volunteer role to fill.
            on_date: The date the new term should start.
            term_days: Length of the new term in days (default 90).

        Returns:
            The newly created :class:`VolunteerRole`, or ``None`` if no
            eligible candidate is available.
        """
        active = self.active_roles(club_id, on_date)
        busy_member_ids = {r.member_id for r in active}

        candidates = [
            m
            for m in self.repo.members_for_club(club_id)
            if m.is_eligible() and m.id not in busy_member_ids
        ]
        if not candidates:
            return None

        # Most reliable first; ties broken by name for deterministic picks.
        best = max(candidates, key=lambda m: (m.reliability_score, m.name))
        return self.assign_role(
            club_id=club_id,
            member_id=best.id,
            role_type=role_type,
            term_start=on_date,
            term_days=term_days,
        )

    def suggest_staggered_start(
        self,
        club_id: str,
        role_type: VolunteerType,
        on_date: date,
    ) -> date:
        """Suggest a start date that staggers a new term after the incumbent.

        If a role of this type is already active, the suggested start is the
        day *after* the latest incumbent's ``term_end`` — so the terms
        overlap up to the handover and there is no gap in coverage. If the
        role is currently uncovered, the suggestion is simply ``on_date`` so
        the gap is closed immediately.

        Args:
            club_id: Club to inspect.
            role_type: The volunteer role being planned.
            on_date: The reference date (fallback when the role is uncovered).

        Returns:
            The suggested ``term_start`` date for the next term.
        """
        active_of_type = [
            r
            for r in self.active_roles(club_id, on_date)
            if r.type == role_type
        ]
        if not active_of_type:
            return on_date
        latest_end = max(r.term_end for r in active_of_type)
        return latest_end + timedelta(days=1)
