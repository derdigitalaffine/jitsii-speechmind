"""ePayBL preparation. No guessed API, no network calls and no activation switch.

The operator's interface/version, credentials and test tenant are required before
an implementation can replace this adapter and complete end-to-end verification.
"""
from dataclasses import dataclass
from typing import Protocol

LABEL = 'ePayBL'
STATUS = 'Noch nicht verfügbar – Anbindung vorbereitet'
REASON = 'Mandant, Schnittstellendokumentation und geprüfte Anbindung fehlen.'


class Unavailable(RuntimeError):
    pass


class Provider(Protocol):
    def ready(self, cfg: dict) -> bool: ...
    def start(self, payment, cfg: dict) -> str: ...
    def refund(self, payment, cents: int, request_id: str, cfg: dict) -> dict: ...
    def reconcile(self, transaction_id: str, cfg: dict) -> dict: ...


@dataclass(frozen=True)
class PreparedProvider:
    def ready(self, cfg: dict) -> bool:
        # Configuration and imported enabled flags must never simulate a working integration.
        return False

    def start(self, payment, cfg: dict) -> str:
        raise Unavailable(f'{STATUS}. {REASON}')

    def refund(self, payment, cents: int, request_id: str, cfg: dict) -> dict:
        raise Unavailable(f'{STATUS}. {REASON}')

    def reconcile(self, transaction_id: str, cfg: dict) -> dict:
        raise Unavailable(f'{STATUS}. {REASON}')


provider = PreparedProvider()


def payment_context(payment) -> dict:
    """Provider-independent data mapping; this is not an ePayBL wire format."""
    return {'reference': payment.ref, 'module': payment.kind, 'subject_id': payment.subject_id,
            'amount_cents': payment.amount_cents, 'currency': payment.currency,
            'purpose': payment.purpose, 'cost_center': payment.cost_center}
