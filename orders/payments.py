"""Simulated payment gateway.

Behaves like Stripe in test mode, so the checkout can show real payment outcomes
(success, declines, 3-D Secure, Apple Pay) without collecting any card details.
The customer picks one of Stripe's published test cards from a list; there is no
card-number field, so real payment data can never be entered (brief §3.1).
Nothing here talks to Stripe or Apple.
"""
import secrets
from dataclasses import dataclass

CARD, APPLE_PAY = "card", "apple_pay"
METHODS = {CARD: "Card", APPLE_PAY: "Apple Pay"}

# id -> (label, brand, last4, outcome, decline message)
# Last-four digits match Stripe's documented test cards.
TEST_CARDS = {
    "visa_ok": ("Payment succeeds", "Visa", "4242", "succeeded", ""),
    "mc_ok": ("Payment succeeds", "Mastercard", "4444", "succeeded", ""),
    "3ds": ("Bank asks for 3-D Secure check", "Visa", "3155", "requires_action", ""),
    "declined": ("Card declined", "Visa", "0002", "declined",
                 "Your card was declined. Try another card or Apple Pay."),
    "no_funds": ("Insufficient funds", "Visa", "9995", "declined",
                 "Your card has insufficient funds. Try another card or Apple Pay."),
    "expired": ("Expired card", "Visa", "0069", "declined",
                "Your card has expired. Try another card or Apple Pay."),
}
# The simulated Apple Pay wallet holds one card.
WALLET_CARD = ("Visa", "4242")


@dataclass
class Payment:
    status: str  # succeeded | requires_action | declined
    method: str
    brand: str = ""
    last4: str = ""
    reference: str = ""
    message: str = ""

    @property
    def ok(self):
        return self.status == "succeeded"


def _reference():
    return "pi_sim_" + secrets.token_hex(8)


def charge_card(card_id):
    """Start a card payment with one of the test cards. Unknown ids are refused."""
    if card_id not in TEST_CARDS:
        return Payment("declined", CARD, message="Choose one of the test cards.")
    _label, brand, last4, outcome, message = TEST_CARDS[card_id]
    return Payment(outcome, CARD, brand, last4, _reference() if outcome == "succeeded" else "", message)


def confirm_3ds(card_id, approved):
    """Finish a payment that needed 3-D Secure."""
    if card_id not in TEST_CARDS or TEST_CARDS[card_id][3] != "requires_action":
        return Payment("declined", CARD, message="This payment cannot be authenticated. Please start again.")
    _label, brand, last4, _o, _m = TEST_CARDS[card_id]
    if not approved:
        return Payment("declined", CARD, brand, last4,
                       message="Your bank could not authenticate the payment. No money was taken.")
    return Payment("succeeded", CARD, brand, last4, _reference())


def charge_wallet():
    brand, last4 = WALLET_CARD
    return Payment("succeeded", APPLE_PAY, brand, last4, _reference())
