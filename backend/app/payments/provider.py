# app/payments/provider.py
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import hmac
from typing import Any, Protocol
import httpx
from ..settings import settings


def to_minor(amount: Decimal | float | int | str) -> int:
    """Converts a currency amount (e.g. INR 945.00) to minor units (e.g. 94500 paise)."""
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class PaymentProvider(Protocol):
    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        receipt: str,
        notes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Creates an order on the provider and returns order dict containing 'id'."""
        ...

    def verify_checkout_signature(
        self,
        order_id: str,
        payment_id: str,
        signature: str,
    ) -> bool:
        """Verifies the client checkout response HMAC signature."""
        ...

    def verify_webhook(
        self,
        raw_body: bytes,
        signature: str,
    ) -> bool:
        """Verifies the webhook delivery HMAC signature over raw body bytes."""
        ...

    async def list_order_payments(
        self,
        order_id: str,
    ) -> list[dict[str, Any]]:
        """Returns payments associated with the order (for reconciliation)."""
        ...


class RazorpayProvider:
    BASE = "https://api.razorpay.com/v1"

    def _client(self) -> httpx.AsyncClient:
        key_id = settings.razorpay_key_id or ""
        key_secret = settings.razorpay_key_secret or ""
        return httpx.AsyncClient(auth=(key_id, key_secret), timeout=10.0)

    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        receipt: str,
        notes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.post(
                f"{self.BASE}/orders",
                json={
                    "amount": amount_minor,
                    "currency": currency,
                    "receipt": receipt,
                    "notes": notes or {},
                },
            )
            r.raise_for_status()
            return r.json()

    def verify_checkout_signature(
        self,
        order_id: str,
        payment_id: str,
        signature: str,
    ) -> bool:
        secret = settings.razorpay_key_secret or ""
        if not secret:
            return False
        expected = hmac.new(
            secret.encode(),
            f"{order_id}|{payment_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    def verify_webhook(
        self,
        raw_body: bytes,
        signature: str,
    ) -> bool:
        secret = settings.razorpay_webhook_secret or ""
        if not secret:
            return False
        expected = hmac.new(
            secret.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    async def list_order_payments(
        self,
        order_id: str,
    ) -> list[dict[str, Any]]:
        async with self._client() as c:
            r = await c.get(f"{self.BASE}/orders/{order_id}/payments")
            r.raise_for_status()
            return r.json().get("items", [])


class MockProvider:
    """Mock provider for development / mock mode."""
    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        receipt: str,
        notes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": f"order_mock_{receipt[:12]}",
            "amount": amount_minor,
            "currency": currency,
            "receipt": receipt,
            "status": "created",
        }

    def verify_checkout_signature(
        self,
        order_id: str,
        payment_id: str,
        signature: str,
    ) -> bool:
        return True

    def verify_webhook(
        self,
        raw_body: bytes,
        signature: str,
    ) -> bool:
        return True

    async def list_order_payments(
        self,
        order_id: str,
    ) -> list[dict[str, Any]]:
        return []


class FakeProvider:
    """
    Test fake provider that tracks state in memory and allows tests to simulate
    real Razorpay behaviors (signature verification, captured payment reconciliation, webhooks).
    """
    def __init__(
        self,
        key_secret: str = "fake_test_key_secret_for_tests",
        webhook_secret: str = "fake_test_webhook_secret_for_tests",
    ):
        self.key_secret = key_secret
        self.webhook_secret = webhook_secret
        self.orders: dict[str, dict[str, Any]] = {}
        self.order_payments: dict[str, list[dict[str, Any]]] = {}
        self.create_order_calls: list[dict[str, Any]] = []

    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        receipt: str,
        notes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        order_id = f"order_fake_{receipt[:12]}_{len(self.orders) + 1}"
        order_data = {
            "id": order_id,
            "amount": amount_minor,
            "currency": currency,
            "receipt": receipt,
            "notes": notes or {},
            "status": "created",
        }
        self.orders[order_id] = order_data
        self.create_order_calls.append(order_data)
        return order_data

    def make_checkout_signature(self, order_id: str, payment_id: str) -> str:
        return hmac.new(
            self.key_secret.encode(),
            f"{order_id}|{payment_id}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def make_webhook_signature(self, raw_body: bytes) -> str:
        return hmac.new(
            self.webhook_secret.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

    def verify_checkout_signature(
        self,
        order_id: str,
        payment_id: str,
        signature: str,
    ) -> bool:
        expected = self.make_checkout_signature(order_id, payment_id)
        return hmac.compare_digest(expected, signature or "")

    def verify_webhook(
        self,
        raw_body: bytes,
        signature: str,
    ) -> bool:
        expected = self.make_webhook_signature(raw_body)
        return hmac.compare_digest(expected, signature or "")

    def add_payment_to_order(
        self,
        order_id: str,
        payment_id: str,
        status: str = "captured",
        amount_minor: int = 1000,
    ) -> None:
        if order_id not in self.order_payments:
            self.order_payments[order_id] = []
        self.order_payments[order_id].append({
            "id": payment_id,
            "order_id": order_id,
            "status": status,
            "amount": amount_minor,
        })

    async def list_order_payments(
        self,
        order_id: str,
    ) -> list[dict[str, Any]]:
        return self.order_payments.get(order_id, [])


# Global provider instance
_active_provider: PaymentProvider = RazorpayProvider()


def get_provider() -> PaymentProvider:
    return _active_provider


def set_provider(p: PaymentProvider) -> None:
    global _active_provider
    _active_provider = p
