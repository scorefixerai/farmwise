"""
FarmWise Farm Logger — Tracks daily production, feed, mortality, sales
Parses natural language entries and stores structured data
"""

import re
import json
import os
import logging
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

# Storage path (use SQLite or a cloud DB in production)
DATA_DIR = os.getenv("DATA_DIR", "./farm_data")


class FarmLogger:
    """Parse and store farm log entries from natural language"""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        # In-memory store keyed by phone number → list of daily entries
        self.logs = defaultdict(list)
        self._load()

    def log_entry(self, phone, text, timestamp):
        """Parse a natural language log entry and store it"""
        entry = self._parse_entry(text)
        entry["timestamp"] = timestamp
        entry["raw"] = text

        self.logs[phone].append(entry)
        self._save(phone)

        return self._format_confirmation(entry)

    def get_weekly_summary(self, phone):
        """Generate a weekly summary for the farmer"""
        entries = self.logs.get(phone, [])
        if not entries:
            return "No records yet. Start logging by telling me what happened today!"

        # Get last 7 days of entries
        recent = entries[-7:] if len(entries) >= 7 else entries

        totals = {
            "eggs_collected": 0,
            "birds_died": 0,
            "feed_bags": 0,
            "feed_kg": 0,
            "sold_amount": 0,
            "sold_revenue": 0,
            "days_logged": len(recent),
        }

        for e in recent:
            totals["eggs_collected"] += e.get("eggs", 0)
            totals["birds_died"] += e.get("mortality", 0)
            totals["feed_bags"] += e.get("feed_bags", 0)
            totals["feed_kg"] += e.get("feed_kg", 0)
            totals["sold_amount"] += e.get("sold_quantity", 0)
            totals["sold_revenue"] += e.get("sold_revenue", 0)

        summary = f"📊 *Your Week ({totals['days_logged']} days logged)*\n\n"

        if totals["eggs_collected"]:
            crates = totals["eggs_collected"] / 30
            summary += f"🥚 Eggs: {totals['eggs_collected']} ({crates:.1f} crates)\n"
        if totals["birds_died"]:
            summary += f"💀 Mortality: {totals['birds_died']} birds\n"
        if totals["feed_bags"]:
            summary += f"🌾 Feed used: {totals['feed_bags']} bags\n"
        if totals["feed_kg"]:
            summary += f"🌾 Feed used: {totals['feed_kg']}kg\n"
        if totals["sold_revenue"]:
            summary += f"💰 Sales: GH₵{totals['sold_revenue']:,.0f}\n"

        # Feed efficiency calculation (if applicable)
        if totals["eggs_collected"] > 0 and totals["feed_kg"] > 0:
            feed_per_egg = totals["feed_kg"] / totals["eggs_collected"] * 1000  # grams
            summary += f"\n📈 Feed per egg: {feed_per_egg:.0f}g"
            if feed_per_egg < 130:
                summary += " (Excellent!)"
            elif feed_per_egg < 150:
                summary += " (Good)"
            else:
                summary += " (Can improve — check feed quality)"

        return summary

    def _parse_entry(self, text):
        """Extract numbers and categories from natural language"""
        text_lower = text.lower()
        entry = {}

        # ── EGGS ──
        egg_patterns = [
            r'(\d+)\s*eggs?',
            r'eggs?\s*[:=]\s*(\d+)',
            r'collected\s*(\d+)',
            r'(\d+)\s*crates?',
        ]
        for pattern in egg_patterns:
            match = re.search(pattern, text_lower)
            if match:
                num = int(match.group(1))
                if 'crate' in text_lower and num < 100:
                    entry["eggs"] = num * 30  # 1 crate = 30 eggs
                else:
                    entry["eggs"] = num
                break

        # ── MORTALITY ──
        death_patterns = [
            r'(\d+)\s*(?:birds?|chickens?|fowls?|fish|pigs?|piglets?)?\s*died',
            r'(?:lost|mortality|dead)\s*[:=]?\s*(\d+)',
            r'lost\s*(\d+)\s*(?:birds?|chickens?|fowls?|fish|pigs?|piglets?)',
            r'(\d+)\s*(?:mortality|dead|lost)',
            r'dead\s*[:=]?\s*(\d+)',
        ]
        for pattern in death_patterns:
            match = re.search(pattern, text_lower)
            if match:
                entry["mortality"] = int(match.group(1))
                break

        # ── FEED ──
        feed_patterns = [
            r'fed\s*(\d+)\s*bags?',
            r'(\d+)\s*bags?\s*(?:of\s*)?feed',
            r'feed\s*[:=]?\s*(\d+)\s*bags?',
            r'(\d+)\s*bags?',
        ]
        for pattern in feed_patterns:
            match = re.search(pattern, text_lower)
            if match:
                entry["feed_bags"] = int(match.group(1))
                entry["feed_kg"] = int(match.group(1)) * 50  # 1 bag = 50kg
                break

        # Also check for kg directly
        kg_match = re.search(r'(\d+)\s*kg\s*(?:of\s*)?feed', text_lower)
        if kg_match:
            entry["feed_kg"] = int(kg_match.group(1))
            if "feed_bags" not in entry:
                entry["feed_bags"] = int(kg_match.group(1)) / 50

        # ── HARVEST (fish/crops) ──
        harvest_patterns = [
            r'harvested?\s*(\d+)\s*(?:kg|kilos?)',
            r'(\d+)\s*(?:kg|kilos?)\s*(?:of\s*)?(?:tilapia|catfish|fish)',
        ]
        for pattern in harvest_patterns:
            match = re.search(pattern, text_lower)
            if match:
                entry["harvest_kg"] = int(match.group(1))
                break

        # ── SALES ──
        sold_patterns = [
            r'sold\s*(\d+)\s*(?:kg|kilos?)',
            r'sold\s*(\d+)\s*(?:birds?|chickens?|pigs?|crates?|fish)',
            r'sold\s*(\d+)',
        ]
        for pattern in sold_patterns:
            match = re.search(pattern, text_lower)
            if match:
                entry["sold_quantity"] = int(match.group(1))
                break

        # Revenue (only count as revenue if "sold" is present, otherwise it's a cost)
        is_sale = 'sold' in text_lower or 'sale' in text_lower
        is_purchase = 'bought' in text_lower or 'purchased' in text_lower
        revenue_patterns = [
            r'(?:gh[₵c¢]?|cedis?|ghs?)\s*(\d+[,.]?\d*)',
            r'(\d+[,.]?\d*)\s*(?:gh[₵c¢]?|cedis?|ghs?)',
            r'for\s*(\d+[,.]?\d*)',
        ]
        for pattern in revenue_patterns:
            match = re.search(pattern, text_lower)
            if match:
                amount = float(match.group(1).replace(',', ''))
                if is_purchase:
                    entry["purchase_cost"] = amount
                elif is_sale:
                    entry["sold_revenue"] = amount
                else:
                    entry["amount_cedis"] = amount
                break

        # ── WEIGHT (for fish/pig) ──
        weight_match = re.search(r'(?:average\s*)?weight\s*[:=]?\s*(\d+\.?\d*)\s*(?:kg|g)', text_lower)
        if weight_match:
            val = float(weight_match.group(1))
            if 'g' in text_lower and val > 10:  # likely grams
                entry["avg_weight_g"] = val
            else:
                entry["avg_weight_g"] = val * 1000 if val < 50 else val

        return entry

    def _format_confirmation(self, entry):
        """Generate a human-readable confirmation"""
        parts = ["✅ Logged:"]

        if "eggs" in entry:
            crates = entry["eggs"] / 30
            parts.append(f"🥚 {entry['eggs']} eggs ({crates:.1f} crates)")
        if "mortality" in entry:
            parts.append(f"💀 {entry['mortality']} died")
        if "feed_bags" in entry:
            parts.append(f"🌾 {entry['feed_bags']} bags feed")
        if "harvest_kg" in entry:
            parts.append(f"🐟 Harvested {entry['harvest_kg']}kg")
        if "sold_quantity" in entry:
            sold_str = f"💰 Sold {entry['sold_quantity']}"
            if "sold_revenue" in entry:
                sold_str += f" for GH₵{entry['sold_revenue']:,.0f}"
            parts.append(sold_str)
        if "purchase_cost" in entry:
            parts.append(f"🛒 Bought for GH₵{entry['purchase_cost']:,.0f}")
        if "avg_weight_g" in entry:
            parts.append(f"⚖️ Avg weight: {entry['avg_weight_g']:.0f}g")

        if len(parts) == 1:
            return (
                "I couldn't understand those numbers. "
                "Try something like: 'Fed 3 bags, collected 200 eggs, 2 birds died'"
            )

        return "\n".join(parts) + "\n\nSend 'summary' anytime for your weekly report."

    def _save(self, phone):
        """Save logs to disk (replace with DB in production)"""
        filepath = os.path.join(DATA_DIR, f"{phone}.json")
        try:
            with open(filepath, "w") as f:
                json.dump(self.logs[phone], f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save logs for {phone}: {e}")

    def _load(self):
        """Load existing logs from disk"""
        try:
            for filename in os.listdir(DATA_DIR):
                if filename.endswith(".json"):
                    phone = filename.replace(".json", "")
                    filepath = os.path.join(DATA_DIR, filename)
                    with open(filepath, "r") as f:
                        self.logs[phone] = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load logs: {e}")
