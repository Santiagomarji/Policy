"""
Orbit — Rotating Social Club
Core domain: models.

Pure standard library. Dataclasses with type hints.
Every model maps to a table in docs/07_Database_Design.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from uuid import uuid4

from .enums import (
    CycleStatus,
    EventStatus,
    EventType,
    GroupStatus,
    MemberRole,
    MemberStatus,
    NotificationChannel,
    NotificationStatus,
    PaymentStatus,
    RsvpStatus,
    SubscriptionStatus,
    SubscriptionTier,
    VolunteerType,
)


def _new_id() -> str:
    """Generate a unique identifier (mirrors DB uuid PK)."""
    return str(uuid4())


@dataclass
class GeoPoint:
    """A simple lat/lng pair used for proximity bucketing."""

    lat: float
    lng: float


@dataclass
class Preference:
    """Member preferences that drive matching (see FR-02, FR-12)."""

    interests: list[str] = field(default_factory=list)
    # availability is a set of day tokens, e.g. {"tue_pm", "thu_pm"}.
    availability: set[str] = field(default_factory=set)
    location: Optional[GeoPoint] = None
    niche: Optional[str] = None
    # Free-form personality tags, e.g. {"introvert"} or {"extrovert"}.
    personality: set[str] = field(default_factory=set)


@dataclass
class Member:
    """A club member.

    reliability_score (0..100) and current_streak power the commitment
    mechanic (FR-30). Both are updated after each event by ReputationService.
    """

    name: str
    club_id: str
    id: str = field(default_factory=_new_id)
    email: str = ""
    phone: str = ""
    verified: bool = False
    reliability_score: int = 100
    current_streak: int = 0
    status: MemberStatus = MemberStatus.ACTIVE
    preference: Preference = field(default_factory=Preference)
    # Per-member secret so a member can only act as themselves (see api auth).
    member_token: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def is_eligible(self) -> bool:
        """Only active members are matched into cycles."""
        return self.status == MemberStatus.ACTIVE


@dataclass
class Membership:
    """Join row: a member belongs to a group for one cycle (see doc 07)."""

    member_id: str
    group_id: str
    role: MemberRole = MemberRole.MEMBER
    is_owner_this_cycle: bool = False
    id: str = field(default_factory=_new_id)
    joined_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Group:
    """A small group of 6-8 members, formed fresh each cycle."""

    club_id: str
    cycle_id: str
    name: str
    id: str = field(default_factory=_new_id)
    member_ids: list[str] = field(default_factory=list)
    owner_id: Optional[str] = None
    streak: int = 0
    status: GroupStatus = GroupStatus.FORMING

    @property
    def size(self) -> int:
        return len(self.member_ids)


@dataclass
class Cycle:
    """A rotation period. Groups are created per-cycle for a clean history."""

    club_id: str
    start_date: date
    end_date: date
    id: str = field(default_factory=_new_id)
    status: CycleStatus = CycleStatus.PLANNED


@dataclass
class Venue:
    """A place events happen. Partner venues back the auto-run fallback."""

    club_id: str
    name: str
    id: str = field(default_factory=_new_id)
    location: Optional[GeoPoint] = None
    vetted: bool = False
    partner: bool = False


@dataclass
class Event:
    """An event. owner_id is None for auto-run fallback events (FR-23).

    For BIG (monthly club-wide) gatherings, ``backup_owner_id`` holds a
    co-host safety net and ``capacity`` caps attendance (overflow -> waitlist).
    ``group_id`` may be empty for club-wide big events (they span all groups).
    """

    group_id: str
    starts_at: datetime
    type: EventType = EventType.SMALL
    id: str = field(default_factory=_new_id)
    venue_id: Optional[str] = None
    owner_id: Optional[str] = None
    backup_owner_id: Optional[str] = None
    club_id: Optional[str] = None      # set for club-wide BIG events
    capacity: Optional[int] = None     # None = unlimited
    status: EventStatus = EventStatus.DRAFT
    is_fallback: bool = False


@dataclass
class Rsvp:
    """A member's response to an event, plus the attendance outcome."""

    event_id: str
    member_id: str
    status: RsvpStatus = RsvpStatus.GOING
    attended: bool = False
    deposit_cents: int = 0
    id: str = field(default_factory=_new_id)


@dataclass
class VolunteerRole:
    """A term-limited club volunteer assignment (FR-52)."""

    member_id: str
    club_id: str
    type: VolunteerType
    term_start: date
    term_end: date
    id: str = field(default_factory=_new_id)


@dataclass
class Rating:
    """A member's 1-5 rating of an event they attended (FR-29)."""

    event_id: str
    member_id: str
    score: int
    comment: Optional[str] = None
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Club:
    """The top-level club/city configuration."""

    name: str
    city: str
    id: str = field(default_factory=_new_id)
    cadence: str = "biweekly+monthly"
    min_density: int = 30


@dataclass
class Subscription:
    """A member's billing subscription (freemium: free or plus).

    ``retry_count`` supports smart-retry on failed renewals (recovers
    involuntary churn — see doc 03). ``cancel_at_period_end`` gives easy,
    honest cancellation without a dark pattern.
    """

    member_id: str
    tier: SubscriptionTier = SubscriptionTier.FREE
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    id: str = field(default_factory=_new_id)
    price_cents: int = 0
    renews_at: Optional[datetime] = None
    cancel_at_period_end: bool = False
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Payment:
    """A single transparent charge (subscription renewal or event deposit)."""

    member_id: str
    amount_cents: int
    description: str
    status: PaymentStatus = PaymentStatus.PENDING
    id: str = field(default_factory=_new_id)
    subscription_id: Optional[str] = None
    event_id: Optional[str] = None
    refunded_cents: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Notification:
    """A scheduled or sent message to a member (reminders, notices).

    Stored in an outbox so delivery is decoupled from scheduling: the
    NotificationService schedules rows, then a worker (or ``dispatch_due``)
    sends the ones whose ``send_at`` has passed via a pluggable sink.
    """

    member_id: str
    kind: str                      # e.g. "event_reminder", "rotation_notice"
    body: str
    send_at: datetime
    channel: NotificationChannel = NotificationChannel.PUSH
    status: NotificationStatus = NotificationStatus.SCHEDULED
    id: str = field(default_factory=_new_id)
    event_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
