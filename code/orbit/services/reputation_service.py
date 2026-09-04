"""
Orbit — Reputation service.

Manages the commitment mechanic (FR-30): each member carries a
``reliability_score`` (0..100) and a ``current_streak``. Attending an event
rewards both; a no-show penalizes the score and breaks the streak.

Pure standard library. Operates on ``Member`` records stored in the
``InMemoryRepository`` (same method names as the production data layer).
"""
from __future__ import annotations

from .repository import InMemoryRepository

# Tuning constants for the commitment mechanic.
REWARD_POINTS: int = 2
PENALTY_POINTS: int = 10
SCORE_MIN: int = 0
SCORE_MAX: int = 100


class ReputationService:
    """Reward attendance and penalize no-shows for members.

    All mutations are applied in place to the ``Member`` objects held by the
    repository, so callers reading through the repo see the updated values.
    """

    def __init__(self, repo: InMemoryRepository) -> None:
        """Bind the service to a repository.

        Args:
            repo: The store holding ``Member`` records to update.
        """
        self.repo = repo

    def reward_attendance(self, member_id: str) -> None:
        """Reward a member for attending an event.

        Increases ``reliability_score`` by :data:`REWARD_POINTS` (capped at
        :data:`SCORE_MAX`) and increments ``current_streak`` by one.

        Args:
            member_id: Id of the member to reward.

        Note:
            No-ops silently if the member is not found, so batch processing
            of an event does not fail on a stale id.
        """
        member = self.repo.members.get(member_id)
        if member is None:
            return
        member.reliability_score = min(SCORE_MAX, member.reliability_score + REWARD_POINTS)
        member.current_streak += 1

    def penalize_no_show(self, member_id: str) -> None:
        """Penalize a member for not showing up.

        Decreases ``reliability_score`` by :data:`PENALTY_POINTS` (floored at
        :data:`SCORE_MIN`) and resets ``current_streak`` to zero.

        Args:
            member_id: Id of the member to penalize.

        Note:
            No-ops silently if the member is not found.
        """
        member = self.repo.members.get(member_id)
        if member is None:
            return
        member.reliability_score = max(SCORE_MIN, member.reliability_score - PENALTY_POINTS)
        member.current_streak = 0

    def process_event_attendance(
        self,
        attended_ids: list[str],
        no_show_ids: list[str],
    ) -> None:
        """Apply rewards and penalties for a completed event.

        Args:
            attended_ids: Member ids who attended (each rewarded).
            no_show_ids: Member ids who were no-shows (each penalized).
        """
        for member_id in attended_ids:
            self.reward_attendance(member_id)
        for member_id in no_show_ids:
            self.penalize_no_show(member_id)

    def get_score(self, member_id: str) -> int:
        """Return the member's current reliability score.

        Args:
            member_id: Id of the member to look up.

        Returns:
            The member's ``reliability_score``.

        Raises:
            KeyError: If no member exists with ``member_id``.
        """
        return self.repo.members[member_id].reliability_score

    def get_streak(self, member_id: str) -> int:
        """Return the member's current attendance streak.

        Args:
            member_id: Id of the member to look up.

        Returns:
            The member's ``current_streak``.

        Raises:
            KeyError: If no member exists with ``member_id``.
        """
        return self.repo.members[member_id].current_streak
