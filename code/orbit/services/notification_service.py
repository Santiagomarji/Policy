"""
Orbit — Notification service.

Schedules and delivers member-facing messages (event reminders, rotation
notices, event announcements) using an *outbox pattern*: scheduling and
delivery are decoupled.

    schedule*  ->  writes SCHEDULED rows into the repository (the outbox)
    dispatch_due  ->  reads the rows whose ``send_at`` has passed and pushes
                      them through a pluggable delivery *sink*

The sink is a ``Callable[[Notification], bool]`` (``True`` means delivered).
Production wires a real push/email/SMS gateway; tests inject a sink that
records calls or simulates failures. The default sink simply returns ``True``.

Pure standard library. Operates on ``Notification`` records stored in the
repository (same method names as the production data layer).
"""
from __future__ import annotations

import datetime
from typing import Callable, Optional

from ..domain.enums import NotificationChannel, NotificationStatus
from ..domain.models import Notification

# Reminder cadence relative to an event's start time: T-3d, T-1d, T-2h.
REMINDER_OFFSETS = [
    datetime.timedelta(days=3),
    datetime.timedelta(days=1),
    datetime.timedelta(hours=2),
]


def _default_sink(notification: Notification) -> bool:
    """Simulated delivery sink used when no sink is injected.

    Args:
        notification: The notification that would be delivered.

    Returns:
        Always ``True`` (pretends delivery always succeeds).
    """
    return True


class NotificationService:
    """Schedule and dispatch member notifications via an outbox.

    Scheduling methods create ``SCHEDULED`` notifications in the repository.
    :meth:`dispatch_due` later pulls the due ones and delivers them through
    the configured ``sink``, flipping each to ``SENT`` or ``FAILED`` in place.
    """

    def __init__(
        self,
        repo,
        sink: Optional[Callable[[Notification], bool]] = None,
    ) -> None:
        """Bind the service to a repository and delivery sink.

        Args:
            repo: The store holding ``Notification``/``Event``/``Rsvp`` records.
            sink: Optional delivery callable taking a ``Notification`` and
                returning ``True`` when delivered. Defaults to a simulated
                sink (:func:`_default_sink`) that always succeeds.
        """
        self.repo = repo
        self.sink: Callable[[Notification], bool] = sink or _default_sink

    def schedule(
        self,
        member_id: str,
        kind: str,
        body: str,
        send_at: datetime.datetime,
        channel: NotificationChannel = NotificationChannel.PUSH,
        event_id: Optional[str] = None,
    ) -> Notification:
        """Create and persist a single SCHEDULED notification.

        Args:
            member_id: Recipient member id.
            kind: Notification category (e.g. ``"event_reminder"``).
            body: Human-readable message body.
            send_at: When the notification becomes due for delivery.
            channel: Delivery channel. Defaults to ``PUSH``.
            event_id: Optional id of the related event.

        Returns:
            The persisted :class:`Notification` (status ``SCHEDULED``).
        """
        notification = Notification(
            member_id=member_id,
            kind=kind,
            body=body,
            send_at=send_at,
            channel=channel,
            status=NotificationStatus.SCHEDULED,
            event_id=event_id,
        )
        return self.repo.add_notification(notification)

    def schedule_event_reminders(
        self,
        event_id: str,
        member_ids: list[str],
    ) -> list[Notification]:
        """Schedule the T-3d / T-1d / T-2h reminder set for an event.

        For each member and each offset in :data:`REMINDER_OFFSETS`, a
        reminder is scheduled at ``event.starts_at - offset``. All three
        reminders are created regardless of whether their computed time lies
        in the future.

        Args:
            event_id: Id of the event to remind about.
            member_ids: Members to notify.

        Returns:
            The list of created :class:`Notification` records.
        """
        event = self.repo.events[event_id]
        created: list[Notification] = []
        for member_id in member_ids:
            for offset in REMINDER_OFFSETS:
                send_at = event.starts_at - offset
                created.append(
                    self.schedule(
                        member_id=member_id,
                        kind="event_reminder",
                        body="Reminder: your Orbit event is coming up",
                        send_at=send_at,
                        channel=NotificationChannel.PUSH,
                        event_id=event_id,
                    )
                )
        return created

    def notify_rotation(
        self,
        member_ids: list[str],
        body: str,
        send_at: Optional[datetime.datetime] = None,
    ) -> list[Notification]:
        """Schedule an (immediate) rotation notice for each member.

        Args:
            member_ids: Members to notify of a new rotation/match.
            body: Message body.
            send_at: When to send. Defaults to now (immediate).

        Returns:
            The list of created ``rotation_notice`` notifications.
        """
        send_at = send_at or datetime.datetime.utcnow()
        created: list[Notification] = []
        for member_id in member_ids:
            created.append(
                self.schedule(
                    member_id=member_id,
                    kind="rotation_notice",
                    body=body,
                    send_at=send_at,
                    channel=NotificationChannel.PUSH,
                )
            )
        return created

    def notify_event_attendees(
        self,
        event_id: str,
        body: str,
        kind: str = "event_notice",
        send_at: Optional[datetime.datetime] = None,
    ) -> list[Notification]:
        """Schedule a notice for every distinct RSVP'd attendee of an event.

        Attendees are derived from ``repo.rsvps_for_event(event_id)``; each
        distinct ``member_id`` is notified once.

        Args:
            event_id: Id of the event whose attendees to notify.
            body: Message body.
            kind: Notification category. Defaults to ``"event_notice"``.
            send_at: When to send. Defaults to now (immediate).

        Returns:
            The list of created notifications (one per distinct attendee).
        """
        send_at = send_at or datetime.datetime.utcnow()
        seen: set[str] = set()
        member_ids: list[str] = []
        for rsvp in self.repo.rsvps_for_event(event_id):
            if rsvp.member_id not in seen:
                seen.add(rsvp.member_id)
                member_ids.append(rsvp.member_id)

        created: list[Notification] = []
        for member_id in member_ids:
            created.append(
                self.schedule(
                    member_id=member_id,
                    kind=kind,
                    body=body,
                    send_at=send_at,
                    channel=NotificationChannel.PUSH,
                    event_id=event_id,
                )
            )
        return created

    def dispatch_due(
        self,
        now: Optional[datetime.datetime] = None,
    ) -> dict:
        """Deliver all notifications whose ``send_at`` has passed.

        Each due (``SCHEDULED``, ``send_at <= now``) notification is pushed
        through the sink. On success it becomes ``SENT`` with ``sent_at=now``;
        on failure it becomes ``FAILED``. Records are mutated in place.

        Args:
            now: Reference time. Defaults to now.

        Returns:
            A summary ``{"sent": int, "failed": int}``.
        """
        now = now or datetime.datetime.utcnow()
        sent = 0
        failed = 0
        for notification in self.repo.due_notifications(now):
            if self.sink(notification):
                notification.status = NotificationStatus.SENT
                notification.sent_at = now
                sent += 1
            else:
                notification.status = NotificationStatus.FAILED
                failed += 1
        return {"sent": sent, "failed": failed}

    def cancel_scheduled(self, notification_id: str) -> None:
        """Cancel a still-scheduled notification.

        No-op if the notification does not exist or has already left the
        ``SCHEDULED`` state (already sent/failed/cancelled).

        Args:
            notification_id: Id of the notification to cancel.
        """
        notification = self.repo.notifications.get(notification_id)
        if notification is not None and notification.status == NotificationStatus.SCHEDULED:
            notification.status = NotificationStatus.CANCELLED

    def pending_for_member(self, member_id: str) -> list[Notification]:
        """Return a member's notifications that are still SCHEDULED.

        Args:
            member_id: Id of the member to query.

        Returns:
            The member's notifications whose status is ``SCHEDULED``.
        """
        return [
            n
            for n in self.repo.notifications_for_member(member_id)
            if n.status == NotificationStatus.SCHEDULED
        ]
