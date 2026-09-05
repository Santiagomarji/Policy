"""
Orbit — Rotating Social Club
Application service: MatchingService.

This is the orchestration layer that sits between the API/CLI and the pure
rotation engine (``orbit.matching.rotation_engine``). Its jobs are:

  1. Create rotation cycles (``create_cycle``).
  2. Translate stored domain objects into the engine's minimal, immutable
     inputs and produce a proposal (``generate_proposal``).
  3. Persist an approved proposal as concrete ``Group`` rows and update the
     shared "who has met whom" history (``commit_proposal``).

The engine itself is pure and does no I/O; all reads/writes live here, going
through the repository. This keeps the matching algorithm trivially testable
and this service the single place where storage side effects happen.

Pure standard library. No third-party dependencies.
"""
from __future__ import annotations

from datetime import date, timedelta

from orbit.domain.models import Cycle, Group, GroupStatus, CycleStatus
from orbit.domain.enums import CycleStatus
from orbit.matching.rotation_engine import (
    RotationEngine,
    RotationInput,
    MemberSnapshot,
    RotationProposal,
)
from orbit.services.repository import InMemoryRepository
from orbit.services.repository_factory import flush_repository


class MatchingService:
    """Orchestrates cycle creation and delegates matching to the engine.

    The service owns no matching logic itself — it gathers state from the
    repository, hands a plain :class:`RotationInput` to the engine, and later
    persists the engine's :class:`RotationProposal`.
    """

    def __init__(
        self,
        repo: InMemoryRepository,
        engine: RotationEngine | None = None,
    ) -> None:
        """Wire the service to a repository and (optionally) a custom engine.

        Args:
            repo: Storage layer for clubs, members, cycles and groups.
            engine: Rotation engine to use. If ``None``, a default
                :class:`RotationEngine` (keep-50/swap-50) is created.
        """
        self.repo = repo
        self.engine = engine if engine is not None else RotationEngine()

    # ------------------------------------------------------------------ #
    # Cycle lifecycle
    # ------------------------------------------------------------------ #
    def create_cycle(
        self,
        club_id: str,
        start_date: date,
        duration_days: int = 14,
    ) -> Cycle:
        """Create a new rotation cycle in ``PLANNED`` status and persist it.

        The cycle's ``end_date`` is derived from ``start_date`` plus
        ``duration_days`` (default 14 — Orbit's biweekly cadence).

        Args:
            club_id: The club this cycle belongs to.
            start_date: First day of the cycle.
            duration_days: Length of the cycle in days (default 14).

        Returns:
            The newly created, persisted :class:`Cycle`.
        """
        cycle = Cycle(
            club_id=club_id,
            start_date=start_date,
            end_date=start_date + timedelta(days=duration_days),
            status=CycleStatus.PLANNED,
        )
        self.repo.add_cycle(cycle)
        return cycle

    def generate_proposal(self, cycle_id: str, seed: int = 0) -> RotationProposal:
        """Build engine inputs from stored state and produce a proposal.

        Steps:
          1. Load the cycle and gather its club's *active* members.
          2. Build an immutable :class:`MemberSnapshot` per member from their
             :class:`Preference` (availability, reliability, niche, and a
             coarse ``area`` key derived from location if present).
          3. Pull prior groups from the latest committed cycle, plus the
             shared ``met_history`` and ``blocks`` from the repository, and the
             set of members who owned a group last cycle.
          4. Run the engine and mark the cycle ``PROPOSED``.

        The cycle is *not* committed here — a Rotation Steward reviews the
        proposal before :meth:`commit_proposal` is called (FR-14).

        Args:
            cycle_id: The cycle to generate a proposal for.
            seed: Deterministic seed forwarded to the engine.

        Returns:
            The engine's :class:`RotationProposal`.

        Raises:
            KeyError: If ``cycle_id`` is not present in the repository.
        """
        cycle = self.repo.cycles[cycle_id]

        # 1. Active members only are matched into cycles.
        members = [
            m
            for m in self.repo.members_for_club(cycle.club_id)
            if m.is_eligible()
        ]

        # 2. Translate each member into the engine's minimal snapshot.
        snapshots: list[MemberSnapshot] = []
        for m in members:
            pref = m.preference
            loc = pref.location
            area = f"{loc.lat:.1f},{loc.lng:.1f}" if loc is not None else "default"
            snapshots.append(
                MemberSnapshot(
                    member_id=m.id,
                    availability=frozenset(pref.availability),
                    reliability_score=m.reliability_score,
                    niche=pref.niche,
                    area=area,
                )
            )

        # 3. Continuity/history inputs from the last committed cycle.
        prior_cycle = self.repo.latest_committed_cycle(cycle.club_id)
        prior_groups: list[list[str]] = []
        previous_owners: set[str] = set()
        if prior_cycle is not None:
            for g in self.repo.groups_for_cycle(prior_cycle.id):
                prior_groups.append(list(g.member_ids))
                if g.owner_id is not None:
                    previous_owners.add(g.owner_id)

        rotation_input = RotationInput(
            members=snapshots,
            prior_groups=prior_groups,
            met_history=self.repo.met_history,
            blocks=self.repo.blocks,
            previous_owners=previous_owners,
            seed=seed,
        )

        # 4. Run the pure engine and record that a proposal exists.
        proposal = self.engine.generate(rotation_input)
        cycle.status = CycleStatus.PROPOSED
        flush_repository(self.repo)
        return proposal

    def commit_proposal(
        self,
        cycle_id: str,
        proposal: RotationProposal,
    ) -> list[Group]:
        """Persist an approved proposal as concrete groups and update history.

        For each :class:`ProposedGroup` this creates a :class:`Group`
        (named ``Orbit-1``, ``Orbit-2`` ...) in ``HEALTHY`` status, stores it,
        and records in ``met_history`` that its members have now met each
        other. Finally the cycle is marked ``COMMITTED``.

        Args:
            cycle_id: The cycle being committed.
            proposal: The (steward-approved) proposal to persist.

        Returns:
            The list of newly created, persisted :class:`Group` objects.

        Raises:
            KeyError: If ``cycle_id`` is not present in the repository.
        """
        cycle = self.repo.cycles[cycle_id]

        groups: list[Group] = []
        for i, pg in enumerate(proposal.groups):
            group = Group(
                club_id=cycle.club_id,
                cycle_id=cycle.id,
                name=f"Orbit-{i + 1}",
                member_ids=list(pg.member_ids),
                owner_id=pg.owner_id,
                status=GroupStatus.HEALTHY,
            )
            self.repo.add_group(group)
            # Everyone in the group has now met everyone else in it.
            self.repo.record_met(group.member_ids)
            groups.append(group)

        cycle.status = CycleStatus.COMMITTED
        flush_repository(self.repo)
        return groups
