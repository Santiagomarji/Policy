"""
Orbit — Group health service.

Monitors the health of small groups (FR-31) by measuring attendance and
owner coverage, and flags groups that are at risk so a rotation steward can
intervene (merge, backfill an owner, or dissolve).

Pure standard library. Reads ``Group``/``Event``/``Rsvp`` records through the
``InMemoryRepository``.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import Group, GroupStatus
from ..domain.enums import EventStatus, GroupStatus
from .repository import InMemoryRepository


@dataclass
class GroupHealthReport:
    """A snapshot of one group's health at assessment time."""

    group_id: str
    group_name: str
    attendance_rate: float  # 0.0 to 1.0
    has_owner: bool
    status: GroupStatus
    at_risk: bool


class HealthService:
    """Assess group health and surface at-risk groups.

    A group is considered at risk when its attendance rate falls below
    ``risk_threshold`` OR it has no owner for the cycle. Assessing an at-risk
    group also transitions its ``status`` to :attr:`GroupStatus.AT_RISK`.
    """

    def __init__(self, repo: InMemoryRepository, risk_threshold: float = 0.5) -> None:
        """Bind the service to a repository and set the risk threshold.

        Args:
            repo: The store holding groups, events, and RSVPs.
            risk_threshold: Minimum acceptable attendance rate (0.0..1.0).
                Groups below this are flagged at risk. Defaults to ``0.5``.
        """
        self.repo = repo
        self.risk_threshold = risk_threshold

    def _attendance_rate(self, group: Group) -> float:
        """Compute attendance rate across the group's completed events.

        Rate is total attended RSVPs divided by total RSVPs over all events
        whose status is :attr:`EventStatus.COMPLETED`.

        Args:
            group: The group to measure.

        Returns:
            Attendance rate in ``0.0..1.0``. Returns ``1.0`` when there are
            no completed events with RSVPs yet, so a brand-new group is not
            penalized for lacking history.
        """
        total_rsvps = 0
        total_attended = 0
        for event in self.repo.events_for_group(group.id):
            if event.status != EventStatus.COMPLETED:
                continue
            for rsvp in self.repo.rsvps_for_event(event.id):
                total_rsvps += 1
                if rsvp.attended:
                    total_attended += 1
        if total_rsvps == 0:
            return 1.0
        return total_attended / total_rsvps

    def assess_group(self, group_id: str) -> GroupHealthReport:
        """Assess a single group and return its health report.

        Computes attendance rate from completed events, checks owner
        coverage, and flags the group at risk if attendance is below the
        threshold or there is no owner. At-risk groups have their ``status``
        set to :attr:`GroupStatus.AT_RISK`.

        Args:
            group_id: Id of the group to assess.

        Returns:
            The :class:`GroupHealthReport` for the group.

        Raises:
            KeyError: If no group exists with ``group_id``.
        """
        group = self.repo.groups[group_id]

        attendance_rate = self._attendance_rate(group)
        has_owner = group.owner_id is not None
        at_risk = attendance_rate < self.risk_threshold or not has_owner

        if at_risk:
            group.status = GroupStatus.AT_RISK

        return GroupHealthReport(
            group_id=group.id,
            group_name=group.name,
            attendance_rate=attendance_rate,
            has_owner=has_owner,
            status=group.status,
            at_risk=at_risk,
        )

    def assess_all_groups(self, cycle_id: str) -> list[GroupHealthReport]:
        """Assess every group in a cycle.

        Args:
            cycle_id: Id of the cycle whose groups to assess.

        Returns:
            One :class:`GroupHealthReport` per group in the cycle.
        """
        return [
            self.assess_group(group.id)
            for group in self.repo.groups_for_cycle(cycle_id)
        ]

    def get_at_risk_groups(self, cycle_id: str) -> list[GroupHealthReport]:
        """Return only the at-risk groups for a cycle.

        Args:
            cycle_id: Id of the cycle to inspect.

        Returns:
            The subset of reports where ``at_risk`` is ``True``.
        """
        return [
            report
            for report in self.assess_all_groups(cycle_id)
            if report.at_risk
        ]
