"""
FarmWise Subscription & Payments
Free trial → MoMo payment → monthly access.
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
DATA_DIR = os.getenv("DATA_DIR", "./farm_data")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
SUBSCRIPTION_PRICE = int(os.getenv("SUBSCRIPTION_PRICE_GHS", "30"))
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "14"))
BASE_URL = os.getenv("BASE_URL", "https://farmwise-bot.onrender.com")

# Admin phones — always have unlimited access (comma-separated in env)
ADMIN_PHONES = [p.strip() for p in os.getenv("ADMIN_PHONES", "").split(",") if p.strip()]


class SubscriptionManager:

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.subs = {}
        self._load()

    def get_or_create(self, phone):
        if phone not in self.subs:
            now = datetime.now(timezone.utc)
            self.subs[phone] = {
                "phone": phone,
                "status": "trial",
                "trial_start": now.isoformat(),
                "trial_end": (now + timedelta(days=TRIAL_DAYS)).isoformat(),
                "paid_until": None,
                "total_paid": 0,
                "payments": [],
            }
            self._save()
        return self.subs[phone]

    def check_access(self, phone):
        """Returns (has_access, message_or_none)"""
        # Admins always have unlimited access
        if phone in ADMIN_PHONES:
            return True, None

        sub = self.get_or_create(phone)
        now = datetime.now(timezone.utc)

        # Paid and active
        if sub["status"] == "active" and sub.get("paid_until"):
            paid_until = datetime.fromisoformat(sub["paid_until"]).replace(tzinfo=timezone.utc) if datetime.fromisoformat(sub["paid_until"]).tzinfo is None else datetime.fromisoformat(sub["paid_until"])
            if now < paid_until:
                days_left = (paid_until - now).days
                if days_left <= 3:
                    return True, f"Your subscription renews in {days_left} day{'s' if days_left!=1 else ''}. Type 'pay' to renew."
                return True, None
            sub["status"] = "expired"
            self._save()

        # Trial
        if sub["status"] == "trial":
            trial_end = datetime.fromisoformat(sub["trial_end"]).replace(tzinfo=timezone.utc) if datetime.fromisoformat(sub["trial_end"]).tzinfo is None else datetime.fromisoformat(sub["trial_end"])
            if now < trial_end:
                days_left = (trial_end - now).days
                if days_left <= 3:
                    return True, f"Your free trial ends in {days_left} day{'s' if days_left!=1 else ''}. Type 'pay' to subscribe — GH₵{SUBSCRIPTION_PRICE}/month."
                return True, None
            sub["status"] = "expired"
            self._save()

        # Expired
        return False, (
            f"Your free trial has ended.\n\n"
            f"Subscribe for GH₵{SUBSCRIPTION_PRICE}/month to continue.\n"
            f"Type *'pay'* to get your MoMo payment link."
        )

    def create_payment_link(self, phone):
        if not PAYSTACK_SECRET_KEY:
            return (
                f"💰 *FarmWise — GH₵{SUBSCRIPTION_PRICE}/month*\n\n"
                f"Send GH₵{SUBSCRIPTION_PRICE} via MoMo to:\n"
                f"MTN MoMo: [YOUR MOMO NUMBER]\n"
                f"Reference: FW-{phone[-4:]}\n\n"
                f"After sending, reply 'done' to activate."
            )
        try:
            resp = requests.post("https://api.paystack.co/transaction/initialize",
                headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"},
                json={
                    "email": f"{phone}@farmwise.app",
                    "amount": SUBSCRIPTION_PRICE * 100,
                    "currency": "GHS",
                    "reference": f"FW-{phone[-4:]}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
                    "callback_url": f"{BASE_URL}/payment/callback",
                    "channels": ["mobile_money"],
                    "metadata": {"phone": phone},
                }, timeout=15)
            if resp.status_code == 200:
                pay_url = resp.json().get("data", {}).get("authorization_url", "")
                return (
                    f"💰 *FarmWise — GH₵{SUBSCRIPTION_PRICE}/month*\n\n"
                    f"Pay with MoMo:\n{pay_url}\n\n"
                    f"Tap the link → Select MoMo → Approve.\n"
                    f"Access activates instantly."
                )
        except Exception as e:
            logger.error(f"Paystack error: {e}")
        return f"Payment link unavailable. Send GH₵{SUBSCRIPTION_PRICE} via MoMo to [YOUR NUMBER] ref FW-{phone[-4:]}."

    def activate(self, phone, days=30, amount=None):
        sub = self.get_or_create(phone)
        now = datetime.now(timezone.utc)
        sub["status"] = "active"
        sub["paid_until"] = (now + timedelta(days=days)).isoformat()
        if amount:
            sub["total_paid"] += amount
            sub["payments"].append({"date": now.isoformat(), "amount": amount})
        self._save()
        return (
            f"✅ *Subscription activated!*\n\n"
            f"Full access for {days} days.\n"
            f"Expires: {(now + timedelta(days=days)).strftime('%B %d, %Y')}\n"
            f"Thank you for supporting FarmWise!"
        )

    def get_status(self, phone):
        sub = self.get_or_create(phone)
        now = datetime.now(timezone.utc)
        if sub["status"] == "trial":
            trial_end = datetime.fromisoformat(sub["trial_end"]).replace(tzinfo=timezone.utc)
            days_left = max(0, (trial_end - now).days)
            return f"📋 *Account*\nStatus: Free Trial ({days_left} days left)\nAfter trial: GH₵{SUBSCRIPTION_PRICE}/month"
        elif sub["status"] == "active":
            paid_until = datetime.fromisoformat(sub["paid_until"]).replace(tzinfo=timezone.utc)
            days_left = max(0, (paid_until - now).days)
            return f"📋 *Account*\nStatus: ✅ Active ({days_left} days left)\nTotal paid: GH₵{sub['total_paid']:,.2f}"
        return f"📋 *Account*\nStatus: ❌ Expired\nType 'pay' to reactivate — GH₵{SUBSCRIPTION_PRICE}/month"

    def handle_webhook(self, event_data):
        if event_data.get("event") != "charge.success":
            return False
        data = event_data.get("data", {})
        phone = data.get("metadata", {}).get("phone", "")
        amount = data.get("amount", 0) / 100
        if phone:
            self.activate(phone, days=30, amount=amount)
            return True
        return False

    def _save(self):
        try:
            with open(os.path.join(DATA_DIR, "subscriptions.json"), "w") as f:
                json.dump(self.subs, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Save error: {e}")

    def _load(self):
        try:
            with open(os.path.join(DATA_DIR, "subscriptions.json"), "r") as f:
                self.subs = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
