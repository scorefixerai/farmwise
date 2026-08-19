"""
FarmWise Invoicing & Payments
Creates invoices, tracks sales, collects payments via MTN MoMo.

Payment flow:
  1. Farmer sells eggs/birds/fish/pigs to a buyer
  2. Farmer tells FarmWise: "sold 5 crates to Kofi for 125 cedis"
  3. FarmWise creates an invoice and can send payment request to buyer via MoMo
  4. Payment is tracked and added to farmer's revenue records

Supported payment providers:
  - Hubtel (Ghana-focused, MTN MoMo + Vodafone Cash + AirtelTigo)
  - Paystack (Pan-African, supports MoMo + cards)
"""

import os
import re
import json
import logging
import requests
from datetime import datetime, timezone
from collections import defaultdict

load_dotenv_available = True
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    load_dotenv_available = False

logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "./farm_data")

# Payment provider config
PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "none")  # "hubtel", "paystack", or "none"
HUBTEL_CLIENT_ID = os.getenv("HUBTEL_CLIENT_ID", "")
HUBTEL_CLIENT_SECRET = os.getenv("HUBTEL_CLIENT_SECRET", "")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")


class InvoiceManager:
    """Create, track, and collect on invoices"""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.invoices = defaultdict(list)
        self._load()

    # ──────────────────────────────────────────
    # INVOICE CREATION
    # ──────────────────────────────────────────

    def create_invoice(self, phone, items, buyer_name="", buyer_phone="", notes=""):
        """
        Create an invoice from a sale.

        items: list of dicts with {description, quantity, unit_price, total}
        Example: [{"description": "Eggs (crates)", "quantity": 5, "unit_price": 25, "total": 125}]
        """
        invoice_id = f"FW-{len(self.invoices[phone]) + 1:04d}"

        grand_total = sum(item.get("total", 0) for item in items)

        invoice = {
            "id": invoice_id,
            "date": datetime.now(timezone.utc).isoformat(),
            "farmer_phone": phone,
            "buyer_name": buyer_name,
            "buyer_phone": buyer_phone,
            "items": items,
            "total": grand_total,
            "currency": "GH₵",
            "status": "unpaid",  # unpaid, paid, partial
            "paid_amount": 0,
            "payment_method": None,
            "notes": notes,
        }

        self.invoices[phone].append(invoice)
        self._save(phone)

        return invoice

    def format_invoice_message(self, invoice):
        """Format invoice as a WhatsApp-friendly text message"""
        msg = f"📄 *INVOICE {invoice['id']}*\n"
        msg += f"Date: {invoice['date'][:10]}\n"
        if invoice["buyer_name"]:
            msg += f"To: {invoice['buyer_name']}\n"
        msg += f"{'─' * 25}\n"

        for item in invoice["items"]:
            desc = item["description"]
            qty = item["quantity"]
            price = item["unit_price"]
            total = item["total"]
            msg += f"{desc}\n"
            msg += f"  {qty} × GH₵{price:,.2f} = GH₵{total:,.2f}\n"

        msg += f"{'─' * 25}\n"
        msg += f"*TOTAL: GH₵{invoice['total']:,.2f}*\n"

        if invoice["status"] == "paid":
            msg += f"✅ PAID via {invoice['payment_method']}\n"
        elif invoice["status"] == "partial":
            remaining = invoice["total"] - invoice["paid_amount"]
            msg += f"⚠️ Paid: GH₵{invoice['paid_amount']:,.2f} | Remaining: GH₵{remaining:,.2f}\n"
        else:
            msg += f"⏳ UNPAID\n"

        if invoice["buyer_phone"]:
            msg += f"\nSend payment request to buyer? Reply 'collect {invoice['id']}'"

        return msg

    def parse_sale(self, text, farm_type):
        """
        Parse natural language sale into invoice items.

        Examples:
        - "sold 5 crates of eggs to Kofi for 125 cedis"
        - "sold 20 birds at 100 each to Ama, phone 0201234567"
        - "sold 50kg tilapia for 2000 cedis"
        - "sold 3 pigs at 4500 each"
        """
        text_lower = text.lower()
        result = {
            "items": [],
            "buyer_name": "",
            "buyer_phone": "",
            "total": 0,
        }

        # Extract buyer name: "to Kofi" or "to Madam Ama"
        buyer_match = re.search(r'to\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)', text)
        if buyer_match:
            result["buyer_name"] = buyer_match.group(1)

        # Extract buyer phone
        phone_match = re.search(r'(?:phone|number|#)\s*(0\d{9})', text_lower)
        if not phone_match:
            phone_match = re.search(r'(0[23]\d{8})', text_lower)
        if phone_match:
            result["buyer_phone"] = phone_match.group(1)

        # Extract quantity and item
        qty = 0
        unit_price = 0
        total = 0
        description = ""

        # "sold 5 crates" or "sold 20 birds" or "sold 50kg"
        qty_match = re.search(r'sold\s+(\d+)\s*(crates?|birds?|chickens?|kg|pigs?|fish|tilapia|catfish)', text_lower)
        if qty_match:
            qty = int(qty_match.group(1))
            unit = qty_match.group(2)

            # Map to description
            if "crate" in unit:
                description = "Eggs (crates)"
            elif "bird" in unit or "chicken" in unit:
                description = "Birds (live)"
            elif "kg" in unit:
                if farm_type == "fish":
                    description = "Fish (kg)"
                else:
                    description = "Meat (kg)"
            elif "pig" in unit:
                description = "Pigs (live)"
            elif "tilapia" in unit:
                description = "Tilapia (kg)"
            elif "catfish" in unit:
                description = "Catfish (kg)"
            else:
                description = unit.capitalize()

        # "at 100 each" or "at 25 per crate"
        price_match = re.search(r'at\s+(\d+)\s*(?:each|per|a)', text_lower)
        if price_match:
            unit_price = float(price_match.group(1))
            total = qty * unit_price

        # "for 125 cedis" or "for GH₵2000"
        total_match = re.search(r'for\s+(?:gh[₵c]?\s*)?(\d+(?:[,.]?\d+)?)\s*(?:cedis?|ghs?)?', text_lower)
        if not total_match:
            total_match = re.search(r'(?:gh[₵c]?\s*)(\d+(?:[,.]?\d+)?)', text_lower)
        if total_match:
            total = float(total_match.group(1).replace(',', ''))
            if qty > 0 and unit_price == 0:
                unit_price = total / qty

        if qty and description:
            result["items"] = [{
                "description": description,
                "quantity": qty,
                "unit_price": unit_price,
                "total": total,
            }]
            result["total"] = total

        return result

    def is_sale_with_invoice(self, text):
        """Detect if a message is a sale that should generate an invoice"""
        text_lower = text.lower()
        has_sold = "sold" in text_lower
        has_to = " to " in text_lower
        has_number = bool(re.search(r'\d+', text_lower))
        has_price = bool(re.search(r'(?:cedis?|ghs?|gh[₵c]|for\s+\d|at\s+\d)', text_lower))
        return has_sold and has_number and (has_to or has_price)

    # ──────────────────────────────────────────
    # PAYMENT COLLECTION
    # ──────────────────────────────────────────

    def request_payment_momo(self, invoice):
        """Send MoMo payment request to buyer"""
        if not invoice.get("buyer_phone"):
            return "No buyer phone number on this invoice. Add it with: 'buyer phone 0201234567'"

        if PAYMENT_PROVIDER == "hubtel":
            return self._hubtel_request(invoice)
        elif PAYMENT_PROVIDER == "paystack":
            return self._paystack_request(invoice)
        else:
            # No payment provider configured — give manual instructions
            buyer = invoice.get("buyer_name", "buyer")
            phone = invoice["buyer_phone"]
            amount = invoice["total"]
            return (
                f"📱 *Send this to {buyer}:*\n\n"
                f"Payment request from FarmWise\n"
                f"Invoice: {invoice['id']}\n"
                f"Amount: GH₵{amount:,.2f}\n"
                f"Pay via MoMo to: [YOUR MOMO NUMBER]\n"
                f"Reference: {invoice['id']}\n\n"
                f"To enable automatic MoMo collection, set up Hubtel or Paystack in your FarmWise settings."
            )

    def mark_paid(self, phone, invoice_id, amount=None, method="MoMo"):
        """Mark an invoice as paid"""
        for inv in self.invoices.get(phone, []):
            if inv["id"] == invoice_id:
                if amount is None:
                    amount = inv["total"]
                inv["paid_amount"] += amount
                inv["payment_method"] = method
                if inv["paid_amount"] >= inv["total"]:
                    inv["status"] = "paid"
                else:
                    inv["status"] = "partial"
                self._save(phone)
                return f"✅ {invoice_id} marked as paid (GH₵{amount:,.2f} via {method})"
        return f"Invoice {invoice_id} not found."

    def get_outstanding(self, phone):
        """Get all unpaid invoices"""
        unpaid = [inv for inv in self.invoices.get(phone, []) if inv["status"] != "paid"]
        if not unpaid:
            return "✅ No outstanding invoices. All paid up!"

        total_owed = sum(inv["total"] - inv["paid_amount"] for inv in unpaid)
        msg = f"📋 *Outstanding Invoices: {len(unpaid)}*\n"
        msg += f"💰 Total owed: GH₵{total_owed:,.2f}\n\n"

        for inv in unpaid[-10:]:  # last 10
            remaining = inv["total"] - inv["paid_amount"]
            buyer = inv.get("buyer_name", "Unknown")
            msg += f"• {inv['id']} — {buyer} — GH₵{remaining:,.2f}\n"

        return msg

    def get_revenue_summary(self, phone, days=30):
        """Revenue summary for last N days"""
        all_inv = self.invoices.get(phone, [])
        if not all_inv:
            return "No sales recorded yet."

        total_revenue = sum(inv["paid_amount"] for inv in all_inv)
        total_invoiced = sum(inv["total"] for inv in all_inv)
        total_outstanding = total_invoiced - total_revenue
        paid_count = sum(1 for inv in all_inv if inv["status"] == "paid")

        msg = f"💰 *Revenue Summary*\n\n"
        msg += f"Total invoiced: GH₵{total_invoiced:,.2f}\n"
        msg += f"Collected: GH₵{total_revenue:,.2f}\n"
        msg += f"Outstanding: GH₵{total_outstanding:,.2f}\n"
        msg += f"Invoices: {len(all_inv)} total, {paid_count} paid\n"

        return msg

    # ──────────────────────────────────────────
    # PAYMENT PROVIDER INTEGRATIONS
    # ──────────────────────────────────────────

    def _hubtel_request(self, invoice):
        """Send payment request via Hubtel API (Ghana MoMo)"""
        try:
            url = "https://api.hubtel.com/v1/merchantaccount/merchants/invoice/create"
            auth = (HUBTEL_CLIENT_ID, HUBTEL_CLIENT_SECRET)
            payload = {
                "items": [{
                    "name": item["description"],
                    "quantity": item["quantity"],
                    "unit_price": item["unit_price"],
                }
                for item in invoice["items"]],
                "total_amount": invoice["total"],
                "description": f"FarmWise Invoice {invoice['id']}",
                "client_reference": invoice["id"],
            }
            resp = requests.post(url, json=payload, auth=auth, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return f"✅ Payment request sent to {invoice['buyer_phone']} via MoMo.\nAmount: GH₵{invoice['total']:,.2f}"
            else:
                logger.error(f"Hubtel error: {resp.status_code} — {resp.text}")
                return "Payment request failed. Please try again or collect manually."
        except Exception as e:
            logger.error(f"Hubtel payment error: {e}")
            return "Payment service unavailable. Please collect manually."

    def _paystack_request(self, invoice):
        """Create payment link via Paystack"""
        try:
            url = "https://api.paystack.co/transaction/initialize"
            headers = {
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "email": f"{invoice['buyer_phone']}@farmwise.local",  # Paystack requires email
                "amount": int(invoice["total"] * 100),  # Paystack uses pesewas
                "currency": "GHS",
                "reference": invoice["id"],
                "callback_url": os.getenv("BASE_URL", "https://farmwise.com") + "/payment/callback",
                "channels": ["mobile_money"],
                "metadata": {
                    "invoice_id": invoice["id"],
                    "buyer_name": invoice.get("buyer_name", ""),
                    "farmer_phone": invoice["farmer_phone"],
                },
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                pay_url = data.get("data", {}).get("authorization_url", "")
                return (
                    f"💳 Payment link created for {invoice.get('buyer_name', 'buyer')}:\n"
                    f"Amount: GH₵{invoice['total']:,.2f}\n"
                    f"Link: {pay_url}\n\n"
                    f"Send this link to your buyer on WhatsApp."
                )
            else:
                return "Payment link creation failed. Please collect manually."
        except Exception as e:
            logger.error(f"Paystack error: {e}")
            return "Payment service unavailable. Please collect manually."

    # ──────────────────────────────────────────
    # STORAGE
    # ──────────────────────────────────────────

    def _save(self, phone):
        filepath = os.path.join(DATA_DIR, f"invoices_{phone}.json")
        try:
            with open(filepath, "w") as f:
                json.dump(self.invoices[phone], f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save invoices: {e}")

    def _load(self):
        try:
            for filename in os.listdir(DATA_DIR):
                if filename.startswith("invoices_") and filename.endswith(".json"):
                    phone = filename.replace("invoices_", "").replace(".json", "")
                    with open(os.path.join(DATA_DIR, filename), "r") as f:
                        self.invoices[phone] = json.load(f)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Failed to load invoices: {e}")
