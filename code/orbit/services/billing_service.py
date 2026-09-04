"""
Orbit — Billing service.

Freemium billing with an anti-"Timeleft" stance (see doc 03): billing is
honest by design.

- **Transparent charges** — every charge records a human-readable
  ``description`` on the :class:`Payment` (e.g. "Orbit Plus monthly",
  "Event deposit"), so a member can always see what they paid for.
- **One-tap cancel** — :meth:`cancel` sets ``cancel_at_period_end`` and the
  member keeps their paid benefits until ``renews_at``. No immediate loss, no
  retention dark patterns, no "call us to cancel".
- **Smart retry** — a failed renewal does not instantly downgrade the member.
  The subscription goes ``PAST_DUE`` and retries up to :data:`MAX_RETRIES`
  times (recovering involuntary churn) before gracefully downgrading to FREE.
- **Refundable event deposits** — big-event deposits are transparent and are
  refunded on attendance via :meth:`refund_deposit`.

The payment gateway is *simulated*: no real network calls. The service takes
an injectable ``gateway`` callable ``(amount_cents) -> bool`` (True = charge
succeeded). The default gateway always succeeds; tests can inject a failing
gateway to exercise the smart-retry and downgrade paths.

Pure standard library. All mutations are applied in place to the model
objects held by the repository, so callers reading through the repo see the
updated values (the in-memory repo returns live objects).
"""
from __future__ import annotations

import datetime
from typing import Callable, Optional

from ..domain.enums import PaymentStatus, SubscriptionStatus, SubscriptionTier
from ..domain.models import Payment, Subscription
from .repository import InMemoryRepository

# --- Module constants --------------------------------------------------- #
PLUS_PRICE_CENTS: int = 900  # $9/mo
MAX_RETRIES: int = 3
RENEWAL_PERIOD_DAYS: int = 30


class BillingService:
    """Manage freemium subscriptions, transparent charges, and deposits.

    Args:
        repo: The store holding ``Subscription`` and ``Payment`` records.
        gateway: An optional simulated payment gateway — a callable mapping
            ``amount_cents -> bool`` where ``True`` means the charge
            succeeded. Defaults to a gateway that always succeeds. Inject a
            failing gateway in tests to exercise retry/downgrade behaviour.
    """

    def __init__(
        self,
        repo: InMemoryRepository,
        gateway: Optional[Callable[[int], bool]] = None,
    ) -> None:
        """Bind the service to a repository and (simulated) gateway."""
        self.repo = repo
        # Default gateway always succeeds (simulated, no real network).
        self.gateway: Callable[[int], bool] = gateway or (lambda amount: True)

    # --- subscriptions -------------------------------------------------- #
    def get_or_create_subscription(self, member_id: str) -> Subscription:
        """Return the member's subscription, creating a FREE one if needed.

        Every member has exactly one subscription. New members start on the
        FREE tier (``price_cents=0``, ``ACTIVE``).

        Args:
            member_id: The member whose subscription to fetch/create.

        Returns:
            The existing or newly created :class:`Subscription`.
        """
        existing = self.repo.subscription_for_member(member_id)
        if existing is not None:
            return existing
        sub = Subscription(
            member_id=member_id,
            tier=SubscriptionTier.FREE,
            status=SubscriptionStatus.ACTIVE,
            price_cents=0,
        )
        return self.repo.add_subscription(sub)

    def subscribe_plus(
        self,
        member_id: str,
        now: Optional[datetime.datetime] = None,
    ) -> dict:
        """Upgrade a member to Orbit Plus, charging the monthly price.

        Records a transparent ``"Orbit Plus monthly"`` payment. On a
        successful charge the subscription becomes PLUS/ACTIVE and its next
        renewal is set 30 days out. On a failed charge the payment is marked
        FAILED and the subscription goes PAST_DUE (the member is not upgraded).

        Args:
            member_id: The member to upgrade.
            now: Reference time (defaults to ``datetime.utcnow()``); used to
                compute ``renews_at``.

        Returns:
            A dict ``{'subscription': Subscription, 'payment': Payment,
            'ok': bool}``.
        """
        now = now or datetime.datetime.utcnow()
        sub = self.get_or_create_subscription(member_id)

        ok = bool(self.gateway(PLUS_PRICE_CENTS))
        payment = Payment(
            member_id=member_id,
            amount_cents=PLUS_PRICE_CENTS,
            description="Orbit Plus monthly",
            status=PaymentStatus.SUCCEEDED if ok else PaymentStatus.FAILED,
            subscription_id=sub.id,
        )
        self.repo.add_payment(payment)

        if ok:
            sub.tier = SubscriptionTier.PLUS
            sub.status = SubscriptionStatus.ACTIVE
            sub.price_cents = PLUS_PRICE_CENTS
            sub.renews_at = now + datetime.timedelta(days=RENEWAL_PERIOD_DAYS)
            sub.cancel_at_period_end = False
            sub.retry_count = 0
        else:
            sub.status = SubscriptionStatus.PAST_DUE

        return {"subscription": sub, "payment": payment, "ok": ok}

    def cancel(self, member_id: str) -> Subscription:
        """Cancel at period end — one tap, honest, no immediate loss.

        Sets ``cancel_at_period_end=True``. The member keeps their paid
        benefits until ``renews_at``; the actual downgrade happens in
        :meth:`process_renewal`. If the member has no subscription yet, a FREE
        one is created (and flagged) so the call is always safe.

        Args:
            member_id: The member cancelling.

        Returns:
            The member's :class:`Subscription`.
        """
        sub = self.get_or_create_subscription(member_id)
        sub.cancel_at_period_end = True
        return sub

    def process_renewal(
        self,
        member_id: str,
        now: Optional[datetime.datetime] = None,
    ) -> dict:
        """Process a subscription renewal (called at ``renews_at``).

        Behaviour:
        - If the member scheduled a cancel (``cancel_at_period_end``), honour
          it: downgrade to FREE/CANCELLED with no further charge.
        - Otherwise attempt to charge the monthly price. On success, record a
          SUCCEEDED payment and extend ``renews_at`` by 30 days.
        - On failure, record a FAILED payment, increment ``retry_count`` and
          mark PAST_DUE (smart retry). Once ``retry_count`` reaches
          :data:`MAX_RETRIES`, gracefully downgrade to FREE/CANCELLED.

        Args:
            member_id: The member whose subscription is renewing.
            now: Reference time (defaults to ``datetime.utcnow()``).

        Returns:
            A result dict. Shapes:
            - cancelled at period end: ``{'renewed': False, 'cancelled': True}``
            - renewed: ``{'renewed': True}``
            - failed charge: ``{'renewed': False, 'retry_count': int,
              'downgraded': bool}``

        Raises:
            ValueError: If the member has no subscription, or it is not PLUS.
        """
        now = now or datetime.datetime.utcnow()
        sub = self.repo.subscription_for_member(member_id)
        if sub is None:
            raise ValueError(f"No subscription for member {member_id!r}")
        if sub.tier != SubscriptionTier.PLUS:
            raise ValueError(
                f"Subscription for member {member_id!r} is not PLUS; "
                "nothing to renew"
            )

        # Honour a scheduled cancellation: downgrade cleanly, no charge.
        if sub.cancel_at_period_end:
            sub.tier = SubscriptionTier.FREE
            sub.status = SubscriptionStatus.CANCELLED
            sub.price_cents = 0
            return {"renewed": False, "cancelled": True}

        ok = bool(self.gateway(PLUS_PRICE_CENTS))
        payment = Payment(
            member_id=member_id,
            amount_cents=PLUS_PRICE_CENTS,
            description="Orbit Plus monthly renewal",
            status=PaymentStatus.SUCCEEDED if ok else PaymentStatus.FAILED,
            subscription_id=sub.id,
        )
        self.repo.add_payment(payment)

        if ok:
            sub.renews_at = now + datetime.timedelta(days=RENEWAL_PERIOD_DAYS)
            sub.retry_count = 0
            sub.status = SubscriptionStatus.ACTIVE
            return {"renewed": True}

        # Failed charge — smart retry, then graceful downgrade.
        sub.retry_count += 1
        sub.status = SubscriptionStatus.PAST_DUE
        downgraded = False
        if sub.retry_count >= MAX_RETRIES:
            sub.tier = SubscriptionTier.FREE
            sub.status = SubscriptionStatus.CANCELLED
            sub.price_cents = 0
            downgraded = True

        return {
            "renewed": False,
            "retry_count": sub.retry_count,
            "downgraded": downgraded,
        }

    # --- event deposits ------------------------------------------------- #
    def charge_event_deposit(
        self,
        member_id: str,
        event_id: str,
        amount_cents: int,
    ) -> Payment:
        """Charge a transparent, refundable deposit for a big event.

        Deposits discourage no-shows for capacity-limited big events and are
        refunded on attendance (see :meth:`refund_deposit`). The charge is
        recorded as a :class:`Payment` tagged with ``event_id`` and a clear
        description, whether it succeeds or fails.

        Args:
            member_id: The member paying the deposit.
            event_id: The big event the deposit is held against.
            amount_cents: The deposit amount, in cents.

        Returns:
            The recorded :class:`Payment` (SUCCEEDED or FAILED).
        """
        ok = bool(self.gateway(amount_cents))
        payment = Payment(
            member_id=member_id,
            amount_cents=amount_cents,
            description="Event deposit",
            status=PaymentStatus.SUCCEEDED if ok else PaymentStatus.FAILED,
            event_id=event_id,
        )
        return self.repo.add_payment(payment)

    def refund_deposit(self, payment_id: str) -> Payment:
        """Refund a previously charged event deposit (attendance -> refund).

        Marks the payment REFUNDED and sets ``refunded_cents`` to the full
        amount. Intended to be called once a member has attended the event
        their deposit was held against.

        Args:
            payment_id: The id of the deposit :class:`Payment` to refund.

        Returns:
            The updated :class:`Payment`.

        Raises:
            ValueError: If no payment with ``payment_id`` exists.
        """
        payment = self.repo.payments.get(payment_id)
        if payment is None:
            raise ValueError(f"No payment with id {payment_id!r}")
        payment.refunded_cents = payment.amount_cents
        payment.status = PaymentStatus.REFUNDED
        return payment
