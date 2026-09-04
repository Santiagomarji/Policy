"""
Orbit — PostgreSQL repository (connects the app to the SQL plan).

Implements the SAME method interface as :class:`InMemoryRepository` /
:class:`JsonFileRepository`, but backed by the PostgreSQL schema defined in
``code/migrations/0001_init.sql``. Because the interface matches, every
service (club, matching, events, reputation, health) and the REST API work
against Postgres with NO changes — just point at this repository.

Driver: ``psycopg`` (v3). It is imported LAZILY inside ``__init__`` so this
module can be imported (and the rest of the app can run on the JSON store)
even on machines where psycopg is not installed. Install with:

    pip install "psycopg[binary]>=3.1"

Apply the schema first:

    psql "$DATABASE_URL" -f code/migrations/0001_init.sql

Then run the API against it (see orbit.services.repository_factory):

    DATABASE_URL=postgres://user:pass@host:5432/orbit python -m orbit.api

Design notes:
  * Reads return freshly-hydrated domain objects (dataclasses), identical in
    shape to what the other repositories return.
  * ``met_history`` and ``blocks`` are exposed as dict-like proxies so engine
    code that does ``repo.met_history.get(id, set())`` keeps working; the
    proxies read/write the ``meeting_history`` / ``block`` tables.
  * Membership is derived: ``group.member_ids`` is stored via the
    ``membership`` join table (one row per member per group).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from ..domain.enums import (
    CycleStatus,
    EventStatus,
    EventType,
    GroupStatus,
    RsvpStatus,
)
from ..domain.models import (
    Club,
    Cycle,
    Event,
    GeoPoint,
    Group,
    Member,
    Preference,
    Rsvp,
    Venue,
)


class _MetHistoryProxy:
    """dict-like view over the meeting_history table.

    Supports the operations the rotation engine and services use:
      * ``proxy[mid]`` / ``proxy.get(mid, default)`` -> set of other member ids
      * ``proxy.setdefault(mid, set())`` -> set (rows are only written via
        ``record_met``; setdefault here just returns current membership)
      * ``mid in proxy``
    """

    def __init__(self, repo: "PostgresRepository") -> None:
        self._repo = repo

    def __getitem__(self, member_id: str) -> set[str]:
        return self._repo._met_for(member_id)

    def get(self, member_id: str, default: Any = None) -> Any:
        found = self._repo._met_for(member_id)
        return found if found else (set() if default is None else default)

    def setdefault(self, member_id: str, default: set[str]) -> set[str]:
        return self._repo._met_for(member_id)

    def __contains__(self, member_id: str) -> bool:
        return bool(self._repo._met_for(member_id))


class _BlocksProxy:
    """dict-like view over the block table (symmetric blocks)."""

    def __init__(self, repo: "PostgresRepository") -> None:
        self._repo = repo

    def __getitem__(self, member_id: str) -> set[str]:
        return self._repo._blocks_for(member_id)

    def get(self, member_id: str, default: Any = None) -> Any:
        found = self._repo._blocks_for(member_id)
        return found if found else (set() if default is None else default)

    def __contains__(self, member_id: str) -> bool:
        return bool(self._repo._blocks_for(member_id))


class PostgresRepository:
    """PostgreSQL-backed repository matching the in-memory interface.

    Args:
        dsn: A libpq connection string / URL, e.g.
            ``postgres://user:pass@host:5432/orbit``.
    """

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # lazy: only needed when actually using Postgres
        except ImportError as e:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "psycopg is required for PostgresRepository. "
                'Install it with: pip install "psycopg[binary]>=3.1"'
            ) from e
        self._psycopg = psycopg
        self.dsn = dsn
        # autocommit keeps the service code (which expects immediate writes,
        # like the JSON repo) working without explicit transaction management.
        self.conn = psycopg.connect(dsn, autocommit=True)
        # Proxies so `repo.met_history` / `repo.blocks` behave like dicts.
        self.met_history = _MetHistoryProxy(self)
        self.blocks = _BlocksProxy(self)
        # Identity map: services mutate objects in place (e.g. group.owner_id,
        # cycle.status, member.reliability_score) and expect those to persist.
        # We cache one instance per id so repeated reads return the SAME object,
        # then flush() writes cached mutations back. The REST API calls flush()
        # at the end of each request (see orbit.services.api).
        self._imap: dict[str, dict[str, Any]] = {
            "member": {}, "cycle": {}, "group": {}, "event": {}, "rsvp": {},
            "subscription": {}, "payment": {}, "notification": {},
            "volunteer_role": {},
        }

    def _cache(self, kind: str, obj_id: str, obj: Any) -> Any:
        """Return the cached instance for (kind, id), storing obj if new."""
        bucket = self._imap[kind]
        if obj_id in bucket:
            return bucket[obj_id]
        bucket[obj_id] = obj
        return obj

    # ------------------------------------------------------------------ #
    # low-level helpers
    # ------------------------------------------------------------------ #
    def _exec(self, sql: str, params: tuple = ()) -> None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)

    def _query(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _query_one(self, sql: str, params: tuple = ()) -> Optional[tuple]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    # ------------------------------------------------------------------ #
    # clubs
    # ------------------------------------------------------------------ #
    def add_club(self, club: Club) -> Club:
        self._exec(
            "INSERT INTO club (id, name, city, cadence, min_density) "
            "VALUES (%s, %s, %s, %s, %s)",
            (club.id, club.name, club.city, club.cadence, club.min_density),
        )
        return club

    @property
    def clubs(self) -> dict[str, Club]:
        rows = self._query(
            "SELECT id, name, city, cadence, min_density FROM club"
        )
        return {r[0]: self._club(r) for r in rows}

    @staticmethod
    def _club(r: tuple) -> Club:
        return Club(id=str(r[0]), name=r[1], city=r[2], cadence=r[3],
                    min_density=r[4])

    # ------------------------------------------------------------------ #
    # members (+ preference row)
    # ------------------------------------------------------------------ #
    def add_member(self, member: Member) -> Member:
        p = member.preference
        loc = p.location
        self._exec(
            "INSERT INTO member (id, club_id, name, email, phone, verified, "
            "reliability_score, current_streak, status, member_token, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (member.id, member.club_id, member.name, member.email, member.phone,
             member.verified, member.reliability_score, member.current_streak,
             member.status.value, member.member_token, member.created_at),
        )
        self._exec(
            "INSERT INTO preference (member_id, interests, availability, lat, "
            "lng, niche, personality) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (member.id, self._json(list(p.interests)),
             self._json(sorted(p.availability)),
             loc.lat if loc else None, loc.lng if loc else None,
             p.niche, self._json(sorted(p.personality))),
        )
        return member

    @property
    def members(self) -> dict[str, Member]:
        rows = self._query(self._MEMBER_SELECT)
        return {str(r[0]): self._cache("member", str(r[0]), self._member(r))
                for r in rows}

    def members_for_club(self, club_id: str) -> list[Member]:
        rows = self._query(self._MEMBER_SELECT + " WHERE m.club_id = %s",
                           (club_id,))
        return [self._cache("member", str(r[0]), self._member(r)) for r in rows]

    _MEMBER_SELECT = (
        "SELECT m.id, m.club_id, m.name, m.email, m.phone, m.verified, "
        "m.reliability_score, m.current_streak, m.status, m.created_at, "
        "p.interests, p.availability, p.lat, p.lng, p.niche, p.personality, "
        "m.member_token "
        "FROM member m LEFT JOIN preference p ON p.member_id = m.id"
    )

    def _member(self, r: tuple) -> Member:
        loc = GeoPoint(r[12], r[13]) if r[12] is not None and r[13] is not None else None
        pref = Preference(
            interests=list(self._unjson(r[10]) or []),
            availability=set(self._unjson(r[11]) or []),
            location=loc,
            niche=r[14],
            personality=set(self._unjson(r[15]) or []),
        )
        created = r[9] if isinstance(r[9], datetime) else datetime.utcnow()
        from ..domain.enums import MemberStatus
        return Member(
            name=r[2], club_id=str(r[1]), id=str(r[0]), email=r[3], phone=r[4],
            verified=r[5], reliability_score=r[6], current_streak=r[7],
            status=MemberStatus(r[8]), preference=pref, created_at=created,
            member_token=r[16],
        )

    # member mutations (services set attributes then rely on repo persistence).
    def save_member(self, member: Member) -> None:
        """Persist mutable member fields (reliability, streak, status)."""
        self._exec(
            "UPDATE member SET reliability_score=%s, current_streak=%s, "
            "status=%s WHERE id=%s",
            (member.reliability_score, member.current_streak,
             member.status.value, member.id),
        )

    # ------------------------------------------------------------------ #
    # cycles
    # ------------------------------------------------------------------ #
    def add_cycle(self, cycle: Cycle) -> Cycle:
        self._exec(
            "INSERT INTO cycle (id, club_id, start_date, end_date, status) "
            "VALUES (%s,%s,%s,%s,%s)",
            (cycle.id, cycle.club_id, cycle.start_date, cycle.end_date,
             cycle.status.value),
        )
        return self._cache("cycle", cycle.id, cycle)

    @property
    def cycles(self) -> dict[str, Cycle]:
        rows = self._query(
            "SELECT id, club_id, start_date, end_date, status FROM cycle"
        )
        return {str(r[0]): self._cache("cycle", str(r[0]), self._cycle(r))
                for r in rows}

    @staticmethod
    def _cycle(r: tuple) -> Cycle:
        return Cycle(id=str(r[0]), club_id=str(r[1]), start_date=r[2],
                     end_date=r[3], status=CycleStatus(r[4]))

    def update_cycle_status(self, cycle_id: str, status: CycleStatus) -> None:
        self._exec("UPDATE cycle SET status=%s WHERE id=%s",
                   (status.value, cycle_id))

    def latest_committed_cycle(self, club_id: str) -> Optional[Cycle]:
        r = self._query_one(
            "SELECT id, club_id, start_date, end_date, status FROM cycle "
            "WHERE club_id=%s AND status=%s ORDER BY start_date DESC LIMIT 1",
            (club_id, CycleStatus.COMMITTED.value),
        )
        return self._cache("cycle", str(r[0]), self._cycle(r)) if r else None

    # ------------------------------------------------------------------ #
    # groups (+ membership join)
    # ------------------------------------------------------------------ #
    def add_group(self, group: Group) -> Group:
        self._exec(
            "INSERT INTO \"group\" (id, club_id, cycle_id, name, owner_id, "
            "streak, status) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (group.id, group.club_id, group.cycle_id, group.name,
             group.owner_id, group.streak, group.status.value),
        )
        for mid in group.member_ids:
            self._exec(
                "INSERT INTO membership (member_id, group_id, is_owner_this_cycle) "
                "VALUES (%s,%s,%s) ON CONFLICT (member_id, group_id) DO NOTHING",
                (mid, group.id, mid == group.owner_id),
            )
        return self._cache("group", group.id, group)

    @property
    def groups(self) -> dict[str, Group]:
        rows = self._query(
            'SELECT id, club_id, cycle_id, name, owner_id, streak, status '
            'FROM "group"'
        )
        return {str(r[0]): self._cache("group", str(r[0]), self._group(r))
                for r in rows}

    def groups_for_cycle(self, cycle_id: str) -> list[Group]:
        rows = self._query(
            'SELECT id, club_id, cycle_id, name, owner_id, streak, status '
            'FROM "group" WHERE cycle_id=%s',
            (cycle_id,),
        )
        return [self._cache("group", str(r[0]), self._group(r)) for r in rows]

    def _group(self, r: tuple) -> Group:
        member_ids = [
            str(x[0]) for x in self._query(
                "SELECT member_id FROM membership WHERE group_id=%s "
                "ORDER BY joined_at, member_id",
                (str(r[0]),),
            )
        ]
        return Group(
            id=str(r[0]), club_id=str(r[1]), cycle_id=str(r[2]), name=r[3],
            member_ids=member_ids, owner_id=str(r[4]) if r[4] else None,
            streak=r[5], status=GroupStatus(r[6]),
        )

    def update_group(self, group: Group) -> None:
        self._exec(
            'UPDATE "group" SET owner_id=%s, status=%s, streak=%s WHERE id=%s',
            (group.owner_id, group.status.value, group.streak, group.id),
        )

    # ------------------------------------------------------------------ #
    # events / rsvps
    # ------------------------------------------------------------------ #
    def add_event(self, event: Event) -> Event:
        # Big events are club-scoped: group_id is "" in the model -> NULL in DB.
        group_id = event.group_id or None
        self._exec(
            "INSERT INTO event (id, group_id, venue_id, owner_id, backup_owner_id, "
            "club_id, capacity, type, starts_at, status, is_fallback) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (event.id, group_id, event.venue_id, event.owner_id,
             event.backup_owner_id, event.club_id, event.capacity,
             event.type.value, event.starts_at, event.status.value,
             event.is_fallback),
        )
        return self._cache("event", event.id, event)

    @property
    def events(self) -> dict[str, Event]:
        rows = self._query(self._EVENT_SELECT)
        return {str(r[0]): self._cache("event", str(r[0]), self._event(r))
                for r in rows}

    def events_for_group(self, group_id: str) -> list[Event]:
        rows = self._query(self._EVENT_SELECT + " WHERE group_id=%s", (group_id,))
        return [self._cache("event", str(r[0]), self._event(r)) for r in rows]

    _EVENT_SELECT = (
        "SELECT id, group_id, venue_id, owner_id, type, starts_at, status, "
        "is_fallback, backup_owner_id, club_id, capacity FROM event"
    )

    @staticmethod
    def _event(r: tuple) -> Event:
        return Event(
            id=str(r[0]),
            group_id=str(r[1]) if r[1] else "",
            venue_id=str(r[2]) if r[2] else None,
            owner_id=str(r[3]) if r[3] else None,
            type=EventType(r[4]), starts_at=r[5], status=EventStatus(r[6]),
            is_fallback=r[7],
            backup_owner_id=str(r[8]) if r[8] else None,
            club_id=str(r[9]) if r[9] else None,
            capacity=r[10],
        )

    def update_event(self, event: Event) -> None:
        self._exec("UPDATE event SET status=%s WHERE id=%s",
                   (event.status.value, event.id))

    def add_rsvp(self, rsvp: Rsvp) -> Rsvp:
        self._exec(
            "INSERT INTO rsvp (id, event_id, member_id, status, attended, "
            "deposit_cents) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (event_id, member_id) DO UPDATE SET status=EXCLUDED.status",
            (rsvp.id, rsvp.event_id, rsvp.member_id, rsvp.status.value,
             rsvp.attended, rsvp.deposit_cents),
        )
        return self._cache("rsvp", rsvp.id, rsvp)

    def rsvps_for_event(self, event_id: str) -> list[Rsvp]:
        rows = self._query(
            "SELECT id, event_id, member_id, status, attended, deposit_cents "
            "FROM rsvp WHERE event_id=%s",
            (event_id,),
        )
        return [self._cache("rsvp", str(r[0]), self._rsvp(r)) for r in rows]

    @staticmethod
    def _rsvp(r: tuple) -> Rsvp:
        return Rsvp(id=str(r[0]), event_id=str(r[1]), member_id=str(r[2]),
                    status=RsvpStatus(r[3]), attended=r[4], deposit_cents=r[5])

    def update_rsvp(self, rsvp: Rsvp) -> None:
        self._exec(
            "UPDATE rsvp SET status=%s, attended=%s WHERE id=%s",
            (rsvp.status.value, rsvp.attended, rsvp.id),
        )

    # ------------------------------------------------------------------ #
    # venues
    # ------------------------------------------------------------------ #
    def add_venue(self, venue: Venue) -> Venue:
        loc = venue.location
        self._exec(
            "INSERT INTO venue (id, club_id, name, lat, lng, vetted, partner) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (venue.id, venue.club_id, venue.name,
             loc.lat if loc else None, loc.lng if loc else None,
             venue.vetted, venue.partner),
        )
        return venue

    @property
    def venues(self) -> dict[str, Venue]:
        rows = self._query(
            "SELECT id, club_id, name, lat, lng, vetted, partner FROM venue"
        )
        return {str(r[0]): self._venue(r) for r in rows}

    def partner_venue(self, club_id: str) -> Optional[Venue]:
        r = self._query_one(
            "SELECT id, club_id, name, lat, lng, vetted, partner FROM venue "
            "WHERE club_id=%s AND partner=true LIMIT 1",
            (club_id,),
        )
        return self._venue(r) if r else None

    @staticmethod
    def _venue(r: tuple) -> Venue:
        loc = GeoPoint(r[3], r[4]) if r[3] is not None and r[4] is not None else None
        return Venue(id=str(r[0]), club_id=str(r[1]), name=r[2], location=loc,
                     vetted=r[5], partner=r[6])

    # ------------------------------------------------------------------ #
    # history / safety
    # ------------------------------------------------------------------ #
    def record_met(self, member_ids: list[str]) -> None:
        for a in member_ids:
            for b in member_ids:
                if a != b:
                    self._exec(
                        "INSERT INTO meeting_history (member_id, other_member_id) "
                        "VALUES (%s,%s) ON CONFLICT (member_id, other_member_id) "
                        "DO NOTHING",
                        (a, b),
                    )

    def add_block(self, a: str, b: str) -> None:
        for x, y in ((a, b), (b, a)):
            self._exec(
                "INSERT INTO block (member_id, blocked_id) VALUES (%s,%s) "
                "ON CONFLICT (member_id, blocked_id) DO NOTHING",
                (x, y),
            )

    def _met_for(self, member_id: str) -> set[str]:
        return {
            str(x[0]) for x in self._query(
                "SELECT other_member_id FROM meeting_history WHERE member_id=%s",
                (member_id,),
            )
        }

    def _blocks_for(self, member_id: str) -> set[str]:
        return {
            str(x[0]) for x in self._query(
                "SELECT blocked_id FROM block WHERE member_id=%s", (member_id,)
            )
        }

    # ------------------------------------------------------------------ #
    # V1 features: volunteer roles, subscriptions, payments, notifications
    # ------------------------------------------------------------------ #
    def add_volunteer_role(self, role):  # type: ignore[no-untyped-def]
        self._exec(
            "INSERT INTO volunteer_role (id, member_id, club_id, type, "
            "term_start, term_end) VALUES (%s,%s,%s,%s,%s,%s)",
            (role.id, role.member_id, role.club_id, role.type.value,
             role.term_start, role.term_end),
        )
        return self._cache("volunteer_role", role.id, role)

    def volunteer_roles_for_club(self, club_id: str):  # type: ignore[no-untyped-def]
        from ..domain.enums import VolunteerType
        from ..domain.models import VolunteerRole
        rows = self._query(
            "SELECT id, member_id, club_id, type, term_start, term_end "
            "FROM volunteer_role WHERE club_id=%s",
            (club_id,),
        )
        out = []
        for r in rows:
            role = VolunteerRole(
                member_id=str(r[1]), club_id=str(r[2]),
                type=VolunteerType(r[3]), term_start=r[4], term_end=r[5],
                id=str(r[0]),
            )
            out.append(self._cache("volunteer_role", role.id, role))
        return out

    def add_subscription(self, sub):  # type: ignore[no-untyped-def]
        self._exec(
            "INSERT INTO subscription (id, member_id, tier, status, price_cents, "
            "renews_at, cancel_at_period_end, retry_count) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (member_id) DO NOTHING",
            (sub.id, sub.member_id, sub.tier.value, sub.status.value,
             sub.price_cents, sub.renews_at, sub.cancel_at_period_end,
             sub.retry_count),
        )
        return self._cache("subscription", sub.id, sub)

    def subscription_for_member(self, member_id: str):  # type: ignore[no-untyped-def]
        from ..domain.enums import SubscriptionStatus, SubscriptionTier
        from ..domain.models import Subscription
        r = self._query_one(
            "SELECT id, member_id, tier, status, price_cents, renews_at, "
            "cancel_at_period_end, retry_count FROM subscription WHERE member_id=%s",
            (member_id,),
        )
        if not r:
            return None
        sub = Subscription(
            member_id=str(r[1]), tier=SubscriptionTier(r[2]),
            status=SubscriptionStatus(r[3]), id=str(r[0]), price_cents=r[4],
            renews_at=r[5], cancel_at_period_end=r[6], retry_count=r[7],
        )
        return self._cache("subscription", sub.id, sub)

    def add_payment(self, payment):  # type: ignore[no-untyped-def]
        self._exec(
            "INSERT INTO payment (id, member_id, amount_cents, description, "
            "status, subscription_id, event_id, refunded_cents) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (payment.id, payment.member_id, payment.amount_cents,
             payment.description, payment.status.value, payment.subscription_id,
             payment.event_id, payment.refunded_cents),
        )
        return self._cache("payment", payment.id, payment)

    def payments_for_member(self, member_id: str):  # type: ignore[no-untyped-def]
        from ..domain.enums import PaymentStatus
        from ..domain.models import Payment
        rows = self._query(
            "SELECT id, member_id, amount_cents, description, status, "
            "subscription_id, event_id, refunded_cents FROM payment "
            "WHERE member_id=%s",
            (member_id,),
        )
        out = []
        for r in rows:
            p = Payment(
                member_id=str(r[1]), amount_cents=r[2], description=r[3],
                status=PaymentStatus(r[4]), id=str(r[0]),
                subscription_id=str(r[5]) if r[5] else None,
                event_id=str(r[6]) if r[6] else None, refunded_cents=r[7],
            )
            out.append(self._cache("payment", p.id, p))
        return out

    def add_notification(self, n):  # type: ignore[no-untyped-def]
        self._exec(
            "INSERT INTO notification (id, member_id, kind, body, send_at, "
            "channel, status, event_id, sent_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (n.id, n.member_id, n.kind, n.body, n.send_at, n.channel.value,
             n.status.value, n.event_id, n.sent_at),
        )
        return self._cache("notification", n.id, n)

    def _notification_row(self, r):  # type: ignore[no-untyped-def]
        from ..domain.enums import NotificationChannel, NotificationStatus
        from ..domain.models import Notification
        n = Notification(
            member_id=str(r[1]), kind=r[2], body=r[3], send_at=r[4],
            channel=NotificationChannel(r[5]), status=NotificationStatus(r[6]),
            id=str(r[0]), event_id=str(r[7]) if r[7] else None, sent_at=r[8],
        )
        return self._cache("notification", n.id, n)

    _NOTIF_SELECT = (
        "SELECT id, member_id, kind, body, send_at, channel, status, "
        "event_id, sent_at FROM notification"
    )

    def notifications_for_member(self, member_id: str):  # type: ignore[no-untyped-def]
        rows = self._query(self._NOTIF_SELECT + " WHERE member_id=%s", (member_id,))
        return [self._notification_row(r) for r in rows]

    def due_notifications(self, now):  # type: ignore[no-untyped-def]
        rows = self._query(
            self._NOTIF_SELECT + " WHERE status='scheduled' AND send_at<=%s",
            (now,),
        )
        return [self._notification_row(r) for r in rows]

    # --- ratings -------------------------------------------------------- #
    def add_rating(self, rating):  # type: ignore[no-untyped-def]
        self._exec(
            "INSERT INTO rating (id, event_id, member_id, score, comment) "
            "VALUES (%s,%s,%s,%s,%s)",
            (rating.id, rating.event_id, rating.member_id, rating.score,
             rating.comment),
        )
        return rating

    def ratings_for_event(self, event_id: str):  # type: ignore[no-untyped-def]
        from ..domain.models import Rating
        rows = self._query(
            "SELECT id, event_id, member_id, score, comment FROM rating "
            "WHERE event_id=%s",
            (event_id,),
        )
        return [
            Rating(event_id=str(r[1]), member_id=str(r[2]), score=r[3],
                   comment=r[4], id=str(r[0]))
            for r in rows
        ]

    # ------------------------------------------------------------------ #
    # json helpers (psycopg adapts lists to jsonb via Json wrapper)
    # ------------------------------------------------------------------ #
    def _json(self, value: Any) -> Any:
        from psycopg.types.json import Json
        return Json(value)

    @staticmethod
    def _unjson(value: Any) -> Any:
        # psycopg returns jsonb already decoded to Python objects.
        return value

    # ------------------------------------------------------------------ #
    # flush: persist in-place mutations made by services
    # ------------------------------------------------------------------ #
    def flush(self) -> None:
        """Write back any in-place mutations on cached objects.

        Services mutate domain objects directly (e.g. ``cycle.status``,
        ``group.owner_id``, ``member.reliability_score``, ``rsvp.attended``,
        ``event.status``). Since Postgres reads return cached instances (the
        identity map), those mutations live on the cached objects; this method
        persists them. The REST API calls ``flush()`` at the end of each
        request so a single call reliably saves everything that changed.
        """
        for m in self._imap["member"].values():
            self.save_member(m)
        for c in self._imap["cycle"].values():
            self.update_cycle_status(c.id, c.status)
        for g in self._imap["group"].values():
            self.update_group(g)
        for e in self._imap["event"].values():
            self.update_event(e)
        for r in self._imap["rsvp"].values():
            self.update_rsvp(r)
        for s in self._imap["subscription"].values():
            self._update_subscription(s)
        for p in self._imap["payment"].values():
            self._update_payment(p)
        for n in self._imap["notification"].values():
            self._update_notification(n)

    def _update_subscription(self, s) -> None:  # type: ignore[no-untyped-def]
        self._exec(
            "UPDATE subscription SET tier=%s, status=%s, price_cents=%s, "
            "renews_at=%s, cancel_at_period_end=%s, retry_count=%s WHERE id=%s",
            (s.tier.value, s.status.value, s.price_cents, s.renews_at,
             s.cancel_at_period_end, s.retry_count, s.id),
        )

    def _update_payment(self, p) -> None:  # type: ignore[no-untyped-def]
        self._exec(
            "UPDATE payment SET status=%s, refunded_cents=%s WHERE id=%s",
            (p.status.value, p.refunded_cents, p.id),
        )

    def _update_notification(self, n) -> None:  # type: ignore[no-untyped-def]
        self._exec(
            "UPDATE notification SET status=%s, sent_at=%s WHERE id=%s",
            (n.status.value, n.sent_at, n.id),
        )

    def clear_cache(self) -> None:
        """Drop the identity map (call after flush, per request)."""
        for bucket in self._imap.values():
            bucket.clear()

    def close(self) -> None:
        self.conn.close()
