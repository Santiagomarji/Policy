"""
Orbit — Rotating Social Club
Service: ClubService.

Handles the club lifecycle plus member registration and the density check
that gates whether a club is viable to run cycles (see FR-01, density
threshold in doc 07). Pure standard library; storage is delegated to the
InMemoryRepository so this is runnable and testable without a database.
"""
from __future__ import annotations

from typing import Optional

from ..domain.models import Club, GeoPoint, Member, Preference
from ..domain.enums import MemberStatus
from .repository import InMemoryRepository


class ClubService:
    """Manage clubs, member registration, and density readiness.

    A club needs a minimum number of members (``min_density``) before it has
    enough people to form healthy rotating groups. This service creates
    clubs, registers members (with their matching preferences) into the
    repository, and reports whether the density threshold has been met.
    """

    def __init__(self, repo: InMemoryRepository) -> None:
        """Bind the service to a storage repository.

        Args:
            repo: The store used to persist clubs and members.
        """
        self.repo = repo

    def create_club(self, name: str, city: str, min_density: int = 30) -> Club:
        """Create a club and persist it.

        Args:
            name: Human-readable club name.
            city: The city the club operates in.
            min_density: Minimum active members needed for the club to run
                cycles. Defaults to 30.

        Returns:
            The newly created and stored ``Club``.
        """
        club = Club(name=name, city=city, min_density=min_density)
        return self.repo.add_club(club)

    def register_member(
        self,
        club_id: str,
        name: str,
        email: str,
        phone: str = "",
        interests: Optional[list[str]] = None,
        availability: Optional[set[str]] = None,
        location: Optional[GeoPoint] = None,
        niche: Optional[str] = None,
        personality: Optional[set[str]] = None,
    ) -> Member:
        """Register a new member in a club.

        Builds the member's matching ``Preference`` from the supplied inputs,
        creates the ``Member`` (defaulting to ``MemberStatus.ACTIVE`` per the
        model), stores it, and then evaluates the club's density so callers
        can react to a newly viable club.

        Args:
            club_id: The id of the club the member joins.
            name: The member's display name.
            email: Contact email.
            phone: Optional contact phone. Defaults to "".
            interests: Optional list of interest tags used for matching.
            availability: Optional set of day tokens (e.g. {"tue_pm"}).
            location: Optional geo point used for proximity bucketing.
            niche: Optional niche/community tag.
            personality: Optional set of free-form personality tags.

        Returns:
            The newly created and stored ``Member``.

        Raises:
            KeyError: If ``club_id`` does not correspond to a known club.
        """
        if club_id not in self.repo.clubs:
            raise KeyError(f"Unknown club_id: {club_id!r}")

        # Mutable defaults are created fresh here to avoid shared state.
        preference = Preference(
            interests=list(interests) if interests is not None else [],
            availability=set(availability) if availability is not None else set(),
            location=location,
            niche=niche,
            personality=set(personality) if personality is not None else set(),
        )
        member = Member(
            name=name,
            club_id=club_id,
            email=email,
            phone=phone,
            status=MemberStatus.ACTIVE,
            preference=preference,
        )
        self.repo.add_member(member)

        # Evaluate density as a side effect so newly-viable clubs are known.
        # The boolean itself is available via check_density(club_id).
        self.check_density(club_id)

        return member

    def check_density(self, club_id: str) -> bool:
        """Report whether a club has reached its minimum density.

        Density is measured against *all* members currently registered to the
        club (matching ``InMemoryRepository.members_for_club``).

        Args:
            club_id: The id of the club to evaluate.

        Returns:
            True if the member count is greater than or equal to the club's
            ``min_density``, otherwise False.

        Raises:
            KeyError: If ``club_id`` does not correspond to a known club.
        """
        club = self.repo.clubs.get(club_id)
        if club is None:
            raise KeyError(f"Unknown club_id: {club_id!r}")

        member_count = len(self.repo.members_for_club(club_id))
        return member_count >= club.min_density

    def get_active_members(self, club_id: str) -> list[Member]:
        """Return the club's members whose status is ACTIVE.

        Args:
            club_id: The id of the club to query.

        Returns:
            A list of ``Member`` objects with ``MemberStatus.ACTIVE``. Empty
            if the club has no active members (or does not exist).
        """
        return [
            m
            for m in self.repo.members_for_club(club_id)
            if m.status == MemberStatus.ACTIVE
        ]
