"""
Orbit — Ratings + post-event follow-up.

The bonding-compounds mechanic (doc 04 sec.4.4 / doc 01 success pattern #4):
a good event isn't the end — the *follow-up* is what turns an event into a
relationship. After an event, members rate it (1-5) and get a nudge to keep in
touch with the people they met, especially those who may rotate to a different
group next cycle.

Pure standard library. Uses the ``Rating`` model / ``rating`` table and the
outbox NotificationService for follow-up prompts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..domain.enums import EventStatus
from ..domain.models import Rating
from .notification_service import NotificationService


class RatingService:
    """Rate events and drive post-event follow-up."""

    def __init__(
        self,
        repo,
        notifications: Optional[NotificationService] = None,
    ) -> None:
        """Bind to a repository and (optionally) a shared NotificationService.

        Args:
            repo: Store holding events, rsvps, ratings, groups, members.
                Must expose ``add_rating``, ``ratings_for_event``, ``events``,
                ``rsvps_for_event``, ``groups``, ``members``.
            notifications: For follow-up prompts. Created on ``repo`` if None.
        """
        self.repo = repo
        self.notifications = notifications or NotificationService(repo)

    # ------------------------------------------------------------------ #
    # rating
    # ------------------------------------------------------------------ #
    def rate_event(
        self,
        event_id: str,
        member_id: str,
        score: int,
        comment: Optional[str] = None,
    ) -> Rating:
        """Record a member's 1-5 rating of an event.

        Args:
            event_id: The event being rated.
            member_id: The rating member.
            score: Integer 1-5.
            comment: Optional free-text comment.

        Returns:
            The persisted :class:`Rating`.

        Raises:
            KeyError: If the event is unknown.
            ValueError: If score is out of range, or the member did not RSVP
                to the event (only attendees may rate).
        """
        if event_id not in self.repo.events:
            raise KeyError(event_id)
        if not 1 <= score <= 5:
            raise ValueError("score must be between 1 and 5")

        # Only people who RSVP'd (attended) may rate — keeps ratings honest.
        rsvp_members = {r.member_id for r in self.repo.rsvps_for_event(event_id)}
        if member_id not in rsvp_members:
            raise ValueError("only attendees can rate this event")

        rating = Rating(event_id=event_id, member_id=member_id, score=score,
                        comment=comment)
        return self.repo.add_rating(rating)

    def event_score(self, event_id: str) -> Optional[float]:
        """Average rating for an event, or ``None`` if unrated."""
        ratings = self.repo.ratings_for_event(event_id)
        if not ratings:
            return None
        return sum(r.score for r in ratings) / len(ratings)

    def event_rating_summary(self, event_id: str) -> dict[str, Any]:
        """Compact rating summary: count, average, and comments."""
        ratings = self.repo.ratings_for_event(event_id)
        return {
            "event_id": event_id,
            "count": len(ratings),
            "average": (sum(r.score for r in ratings) / len(ratings))
            if ratings else None,
            "comments": [r.comment for r in ratings if r.comment],
        }

    # ------------------------------------------------------------------ #
    # follow-up
    # ------------------------------------------------------------------ #
    def send_follow_ups(
        self,
        event_id: str,
        now: Optional[datetime] = None,
    ) -> list:
        """Prompt each attendee to keep in touch with the people they met.

        For a completed event, sends every attendee a follow-up notification
        naming their fellow attendees — the connective tissue that turns an
        event into a friendship. Returns the created notifications.

        Args:
            event_id: The (ideally completed) event to follow up on.
            now: Timestamp for the notifications (default utcnow).

        Returns:
            The list of created follow-up notifications (one per attendee with
            at least one other attendee to reconnect with).

        Raises:
            KeyError: If the event is unknown.
        """
        event = self.repo.events[event_id]
        now = now or datetime.utcnow()

        # Attendees who actually showed up (attended=True), else those who RSVP'd.
        rsvps = self.repo.rsvps_for_event(event_id)
        attended = [r.member_id for r in rsvps if r.attended]
        attendees = attended if attended else [r.member_id for r in rsvps]

        created = []
        for member_id in attendees:
            others = [mid for mid in attendees if mid != member_id]
            if not others:
                continue
            names = ", ".join(
                self.repo.members[o].name
                for o in others
                if o in self.repo.members
            )
            created.append(self.notifications.schedule(
                member_id=member_id,
                kind="follow_up",
                body=f"Enjoyed the event? Keep in touch with {names}.",
                send_at=now,
                event_id=event_id,
            ))
        return created
