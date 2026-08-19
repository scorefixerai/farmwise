"""
FarmWise Farm State Manager
Tracks each farmer's animals: batches, counts, ages, and growth milestones.
This is what makes FarmWise an agent, not just a chatbot.

A "batch" is a group of animals that started together:
  - 500 day-old broiler chicks bought on March 1
  - 200 layer pullets bought at 16 weeks on Feb 15
  - 1000 tilapia fingerlings stocked on Jan 10
"""

import json
import os
import re
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)
DATA_DIR = os.getenv("DATA_DIR", "./farm_data")


# ──────────────────────────────────────────────
# GROWTH MILESTONES — what needs to happen at each age
# ──────────────────────────────────────────────

POULTRY_BROILER_MILESTONES = [
    {"day": 1,  "action": "Vaccinate: ND HB1 eye drop. Keep brooder at 33°C. Provide sugar water for first 4 hours."},
    {"day": 3,  "action": "Check brooder temperature (31-32°C). Birds should be active and spread evenly. Start antibiotics if stressed."},
    {"day": 7,  "action": "Vaccinate: Gumboro (in water). Weigh a sample of 10 birds — target 170-180g."},
    {"day": 10, "action": "Reduce brooder temp to 28°C. Birds should be eating well. Check for pasty vents."},
    {"day": 14, "action": "Vaccinate: ND La Sota (in water). Weigh sample — target 450-500g. Switch from starter to grower feed if not done."},
    {"day": 21, "action": "Vaccinate: Gumboro booster (in water). Weigh sample — target 850-900g. Remove brooder guards."},
    {"day": 28, "action": "Vaccinate: ND La Sota booster. Weigh sample — target 1.3-1.5kg. Full ventilation now."},
    {"day": 35, "action": "Weigh sample — target 1.8-2.0kg. Switch to finisher feed. Start planning market/sales."},
    {"day": 42, "action": "Weigh sample — target 2.2-2.5kg. Birds approaching market weight. Contact your buyers."},
    {"day": 49, "action": "Market weight reached (2.5-3.0kg). Sell or process. Keeping birds past 8 weeks increases feed cost without proportional weight gain."},
]

POULTRY_LAYER_MILESTONES = [
    {"day": 1,   "action": "Vaccinate: ND HB1 eye drop. Brooder at 33°C. Sugar water first 4 hours."},
    {"day": 7,   "action": "Vaccinate: Gumboro (in water)."},
    {"day": 14,  "action": "Vaccinate: ND La Sota (in water). Weigh sample."},
    {"day": 21,  "action": "Vaccinate: Gumboro booster (in water)."},
    {"day": 28,  "action": "Vaccinate: ND La Sota booster."},
    {"day": 42,  "action": "Vaccinate: Fowl Pox (wing web method). This is critical — don't skip."},
    {"day": 56,  "action": "Move to grower house if separate. Reduce protein to 18-19%."},
    {"day": 84,  "action": "12 weeks old. Deworm with Piperazine. Weigh — target 1.0-1.1kg."},
    {"day": 112, "action": "16 weeks. Vaccinate: ND + IB booster. Start pre-layer feed (2.5% calcium). Increase light to 14 hours/day."},
    {"day": 126, "action": "18 weeks. Switch to layer feed (16-17% protein, 3.5-4% calcium). Expect first eggs in 2-4 weeks."},
    {"day": 140, "action": "20 weeks. Point of lay — you should see first eggs now. If not, check feed quality and lighting."},
    {"day": 154, "action": "22 weeks. Production should be climbing (30-50%). Record daily egg count."},
    {"day": 182, "action": "26 weeks. Peak production approaching (85-95%). Vaccinate: ND La Sota. This is your best earning period."},
    {"day": 270, "action": "38 weeks. Production may start declining. Ensure calcium intake. Consider adding oyster shell."},
    {"day": 365, "action": "52 weeks. Review flock performance. Plan for replacement flock 8 weeks before culling."},
    {"day": 504, "action": "72 weeks. Production dropping below 65%. Time to plan culling and replacement."},
]

FISH_TILAPIA_MILESTONES = [
    {"day": 1,   "action": "Stocking day. Acclimatize fingerlings — float bags in pond for 20 min before releasing. Feed 5-8% body weight with 40-45% protein feed."},
    {"day": 14,  "action": "2 weeks. Check for mortalities. Remove dead fish immediately. Sample weight — target 5-10g."},
    {"day": 30,  "action": "1 month. Reduce feeding to 3-5% body weight. Check water quality (pH, oxygen). Weigh — target 20-30g."},
    {"day": 60,  "action": "2 months. Switch to 35% protein juvenile feed. Reduce feeding to 3% body weight. Weigh — target 50-80g."},
    {"day": 90,  "action": "3 months. Switch to 28-32% grow-out feed. Check stocking density. Weigh — target 100-150g."},
    {"day": 120, "action": "4 months. Weigh sample — target 200-250g. If below target, check feed quality and water."},
    {"day": 150, "action": "5 months. Weigh — target 300-350g. Start identifying market buyers."},
    {"day": 180, "action": "6 months. Market size approaching (400-500g). Partial harvest of largest fish possible."},
    {"day": 210, "action": "7 months. Full harvest recommended (400-600g). Keeping longer increases feed cost with slow growth."},
]

FISH_CATFISH_MILESTONES = [
    {"day": 1,   "action": "Stocking day. Acclimatize. Sort by size if possible — catfish are cannibalistic. Feed 5-8% body weight."},
    {"day": 14,  "action": "2 weeks. Sort again by size — remove runts. This prevents cannibalism."},
    {"day": 30,  "action": "1 month. Reduce feeding to 3-5%. Feed at dusk (catfish are nocturnal feeders)."},
    {"day": 60,  "action": "2 months. Switch to 35% protein feed. Weigh — target 100-200g."},
    {"day": 90,  "action": "3 months. Weigh — target 300-500g. Switch to 28% grow-out feed."},
    {"day": 120, "action": "4 months. Market size for catfish (700g-1kg). Start selling or plan harvest."},
    {"day": 150, "action": "5 months. Harvest recommended. Target 1-1.5kg. Catfish beyond this grow slowly."},
]

PIG_MILESTONES = [
    {"day": 1,   "action": "Arrival/birth day. Ensure warmth (creep area 30-32°C for piglets). Iron injection within 3 days. Navel care."},
    {"day": 3,   "action": "Iron injection (Dextran, 1ml). Clip needle teeth if sharp. Check sow milk supply."},
    {"day": 7,   "action": "Start offering creep feed. Check for diarrhea — treat with ORS + Colistin if present."},
    {"day": 14,  "action": "2 weeks. Males to be castrated if intended for market (optional). Weigh — target 3-5kg."},
    {"day": 28,  "action": "4 weeks. Weaning time. Separate from sow. Start weaner feed (18-20% protein). Deworm with Ivermectin."},
    {"day": 56,  "action": "8 weeks. Switch to grower feed (16% protein). Weigh — target 15-20kg. Vaccinate if required by local vet."},
    {"day": 84,  "action": "12 weeks. Deworm again. Weigh — target 30-40kg. Adjust feed amount (2-3kg/day)."},
    {"day": 112, "action": "16 weeks. Weigh — target 50-60kg. Increase feed to 3-3.5kg/day. Market planning."},
    {"day": 140, "action": "20 weeks. Weigh — target 70-80kg. Reduce protein to 14% (finisher feed)."},
    {"day": 168, "action": "24 weeks (6 months). Market weight (80-100kg). Sell for best price. Feed efficiency drops sharply after this."},
]

MILESTONE_MAP = {
    "poultry_broiler": POULTRY_BROILER_MILESTONES,
    "poultry_layer": POULTRY_LAYER_MILESTONES,
    "fish_tilapia": FISH_TILAPIA_MILESTONES,
    "fish_catfish": FISH_CATFISH_MILESTONES,
    "pig": PIG_MILESTONES,
}


class FarmState:
    """Manages the state of each farmer's operation"""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.farms = {}
        self._load_all()

    def get_farm(self, phone):
        """Get or create a farm profile"""
        if phone not in self.farms:
            self.farms[phone] = {
                "farm_type": None,
                "batches": [],
                "created": datetime.now(timezone.utc).isoformat(),
            }
        return self.farms[phone]

    # ──────────────────────────────────────────
    # BATCH MANAGEMENT
    # ──────────────────────────────────────────

    def add_batch(self, phone, batch_type, count, start_date=None, start_age_days=0, breed=""):
        """
        Register a new batch of animals.
        batch_type: broiler, layer, tilapia, catfish, pig
        count: number of animals
        start_date: when they arrived (default: today)
        start_age_days: age when acquired (e.g., 0 for day-old, 112 for 16-week layers)
        """
        farm = self.get_farm(phone)

        if start_date is None:
            start_date = datetime.now(timezone.utc)
        elif isinstance(start_date, str):
            try:
                start_date = datetime.fromisoformat(start_date)
            except ValueError:
                start_date = datetime.now(timezone.utc)

        batch_id = len(farm["batches"]) + 1
        batch = {
            "id": batch_id,
            "type": batch_type,
            "breed": breed,
            "initial_count": count,
            "current_count": count,
            "start_date": start_date.isoformat(),
            "start_age_days": start_age_days,
            "mortality_total": 0,
            "sold_total": 0,
            "added_total": 0,
            "notes": [],
            "active": True,
        }
        farm["batches"].append(batch)
        self._save(phone)

        age = self._get_age_days(batch)
        age_str = self._format_age(age)

        response = (
            f"✅ Registered: {count} {batch_type}"
            f"{f' ({breed})' if breed else ''}\n"
            f"📋 Batch #{batch_id} • Age: {age_str}\n"
            f"📊 I'll track their growth and remind you of key milestones.\n\n"
        )

        # Show immediate milestone
        next_ms = self._get_next_milestone(batch)
        if next_ms:
            days_until = next_ms["day"] - age
            if days_until <= 0:
                response += f"⚡ TODAY: {next_ms['action']}"
            else:
                response += f"📅 Next milestone (Day {next_ms['day']}, in {days_until} days):\n{next_ms['action']}"

        return response

    def update_count(self, phone, batch_id, died=0, sold=0, added=0):
        """Update animal count for a batch"""
        farm = self.get_farm(phone)

        batch = self._find_batch(farm, batch_id)
        if not batch:
            return f"Batch #{batch_id} not found. Type 'farm' to see your batches."

        batch["current_count"] = batch["current_count"] - died - sold + added
        batch["mortality_total"] += died
        batch["sold_total"] += sold
        batch["added_total"] += added

        if batch["current_count"] <= 0:
            batch["active"] = False
            batch["current_count"] = 0

        self._save(phone)

        parts = []
        if died: parts.append(f"💀 {died} died")
        if sold: parts.append(f"💰 {sold} sold")
        if added: parts.append(f"➕ {added} added")

        status = " • ".join(parts)
        remaining = batch["current_count"]
        mortality_pct = (batch["mortality_total"] / batch["initial_count"] * 100) if batch["initial_count"] > 0 else 0

        response = f"✅ Batch #{batch_id} updated: {status}\n"
        response += f"📊 Remaining: {remaining} of {batch['initial_count']} ({mortality_pct:.1f}% total mortality)\n"

        if mortality_pct > 5:
            response += f"\n⚠️ Your mortality rate ({mortality_pct:.1f}%) is above the 5% target. Consider reviewing biosecurity and feed quality."

        return response

    def get_farm_summary(self, phone):
        """Generate a full farm status report"""
        farm = self.get_farm(phone)
        batches = [b for b in farm["batches"] if b["active"]]

        if not batches:
            return (
                "📋 You don't have any active batches registered.\n\n"
                "To register animals, tell me something like:\n"
                "• 'I have 500 broiler chicks, 1 week old'\n"
                "• 'I bought 200 layer pullets today'\n"
                "• 'I stocked 1000 tilapia fingerlings'\n"
                "• 'I have 10 weaner pigs'"
            )

        response = f"📋 *Your Farm — {len(batches)} active batch{'es' if len(batches) > 1 else ''}*\n\n"

        total_animals = 0
        for b in batches:
            age = self._get_age_days(b)
            age_str = self._format_age(age)
            mort_pct = (b["mortality_total"] / b["initial_count"] * 100) if b["initial_count"] > 0 else 0

            response += f"*Batch #{b['id']}:* {b['current_count']} {b['type']}"
            if b["breed"]:
                response += f" ({b['breed']})"
            response += f"\n"
            response += f"  Age: {age_str} • Started with {b['initial_count']}\n"
            if b["mortality_total"] > 0:
                response += f"  Lost: {b['mortality_total']} ({mort_pct:.1f}% mortality)\n"
            if b["sold_total"] > 0:
                response += f"  Sold: {b['sold_total']}\n"

            # Next milestone
            next_ms = self._get_next_milestone(b)
            if next_ms:
                days_until = next_ms["day"] - age
                if days_until <= 0:
                    response += f"  ⚡ DUE NOW: {next_ms['action'][:60]}...\n"
                elif days_until <= 3:
                    response += f"  📅 In {days_until} day{'s' if days_until > 1 else ''}: {next_ms['action'][:60]}...\n"

            response += "\n"
            total_animals += b["current_count"]

        response += f"*Total animals: {total_animals}*"
        return response

    def get_daily_advice(self, phone):
        """Generate proactive daily advice based on current farm state"""
        farm = self.get_farm(phone)
        batches = [b for b in farm["batches"] if b["active"]]

        if not batches:
            return None

        advice_parts = []
        for b in batches:
            age = self._get_age_days(b)

            # Check for milestones due today or overdue
            milestone_key = self._get_milestone_key(b)
            milestones = MILESTONE_MAP.get(milestone_key, [])

            for ms in milestones:
                days_diff = ms["day"] - age
                if days_diff == 0:
                    advice_parts.append(f"⚡ Batch #{b['id']} ({b['current_count']} {b['type']}, Day {age}):\n{ms['action']}")
                elif days_diff == 1:
                    advice_parts.append(f"📅 Tomorrow — Batch #{b['id']} ({b['type']}, Day {age + 1}):\n{ms['action']}")
                elif days_diff == -1:
                    advice_parts.append(f"⚠️ OVERDUE — Batch #{b['id']} ({b['type']}, was due Day {ms['day']}):\n{ms['action']}")

        if not advice_parts:
            return None

        return "🌅 *FarmWise Daily Update*\n\n" + "\n\n".join(advice_parts)

    # ──────────────────────────────────────────
    # NATURAL LANGUAGE PARSING
    # ──────────────────────────────────────────

    def parse_registration(self, text, farm_type):
        """
        Parse natural language like:
        - 'I have 500 broiler chicks'
        - 'I bought 200 day old layers today'
        - 'I stocked 1000 tilapia fingerlings 2 weeks ago'
        - 'I have 10 weaner pigs, 8 weeks old'
        """
        text_lower = text.lower()
        result = {"count": None, "batch_type": None, "breed": "", "age_days": 0}

        # Extract count — prioritize "I have 300" over "308 broilers"
        count_match = re.search(r'(?:have|bought|got|stocked|received|started\s+with|just\s+bought|just\s+got)\s+(\d+)', text_lower)
        if not count_match:
            count_match = re.search(r'^(\d+)\s', text_lower)
        if not count_match:
            count_match = re.search(r'(\d+)\s*(?:day.old|week.old)?\s*(?:broiler|layer|chick|pullet|bird|tilapia|catfish|fish|fingerling|pig|weaner|piglet|sow|gilt)', text_lower)
        if count_match:
            result["count"] = int(count_match.group(1))

        # Determine batch type
        if farm_type == "poultry":
            if any(w in text_lower for w in ["broiler", "meat bird", "cobb", "ross"]):
                result["batch_type"] = "broiler"
            elif any(w in text_lower for w in ["layer", "pullet", "lohmann", "isa brown", "egg"]):
                result["batch_type"] = "layer"
            else:
                result["batch_type"] = "broiler"  # default for poultry

            # Breed detection
            if "cobb" in text_lower:
                result["breed"] = "Cobb 500"
            elif "ross" in text_lower:
                result["breed"] = "Ross 308"
            elif "lohmann" in text_lower:
                result["breed"] = "Lohmann Brown"
            elif "isa" in text_lower:
                result["breed"] = "ISA Brown"

        elif farm_type == "fish":
            if "catfish" in text_lower or "clarias" in text_lower:
                result["batch_type"] = "catfish"
            else:
                result["batch_type"] = "tilapia"

        elif farm_type == "pig":
            result["batch_type"] = "pig"
            if "large white" in text_lower:
                result["breed"] = "Large White"
            elif "landrace" in text_lower:
                result["breed"] = "Landrace"
            elif "ashanti" in text_lower:
                result["breed"] = "Ashanti Black"

        # Extract age — "day old" = age 0, "X weeks old" = X*7
        if "day.old" in text_lower.replace(" ", ".") or "day old" in text_lower:
            # "500 day old chicks" = age 0, not 500
            # But "5 days old" = age 5
            specific = re.search(r'(\d+)\s*days?\s*old', text_lower)
            if specific and int(specific.group(1)) != result.get("count", -1) and int(specific.group(1)) < 100:
                result["age_days"] = int(specific.group(1))
            else:
                result["age_days"] = 0
        else:
            week_match = re.search(r'(\d+)\s*(?:week|weeks|wk|wks)\s*old', text_lower)
            if week_match:
                result["age_days"] = int(week_match.group(1)) * 7
            elif "weaner" in text_lower or "weanling" in text_lower:
                result["age_days"] = 28
            elif "pullet" in text_lower:
                result["age_days"] = 112
            elif "fingerling" in text_lower:
                result["age_days"] = 14

        return result

    def is_registration(self, text):
        """Detect if a message is registering animals"""
        text_lower = text.lower()
        reg_verbs = ["i have", "i bought", "i got", "i stocked", "i received", "i started with", "just bought", "just got", "new batch", "register"]
        animal_words = ["broiler", "layer", "chick", "pullet", "bird", "tilapia", "catfish", "fish", "fingerling", "pig", "weaner", "piglet", "sow"]

        has_verb = any(v in text_lower for v in reg_verbs)
        has_animal = any(a in text_lower for a in animal_words)
        has_number = bool(re.search(r'\d+', text_lower))

        return has_verb and has_animal and has_number

    # ──────────────────────────────────────────
    # CONTEXT FOR LLM
    # ──────────────────────────────────────────

    def get_context_for_llm(self, phone):
        """Generate a context string to prepend to LLM queries"""
        farm = self.get_farm(phone)
        batches = [b for b in farm["batches"] if b["active"]]

        if not batches:
            return ""

        context = "\n--- FARMER'S CURRENT FARM STATE ---\n"
        for b in batches:
            age = self._get_age_days(b)
            age_str = self._format_age(age)
            breed_str = f" ({b['breed']})" if b['breed'] else ""
            context += (
                f"Batch #{b['id']}: {b['current_count']} {b['type']}"
                f"{breed_str}"
                f", age {age_str} (Day {age})"
                f", started with {b['initial_count']}"
                f", {b['mortality_total']} died so far"
                f"\n"
            )

            # Include current and next milestones
            next_ms = self._get_next_milestone(b)
            if next_ms:
                days_until = next_ms["day"] - age
                context += f"  Next milestone: Day {next_ms['day']} ({days_until} days away): {next_ms['action']}\n"

        context += "--- END FARM STATE ---\n"
        context += "Use this information to give personalized advice. Reference their specific batch numbers, ages, and counts.\n"
        return context

    # ──────────────────────────────────────────
    # INTERNAL HELPERS
    # ──────────────────────────────────────────

    def _get_age_days(self, batch):
        """Calculate current age in days"""
        start = datetime.fromisoformat(batch["start_date"])
        now = datetime.now(timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        elapsed = (now - start).days
        return elapsed + batch.get("start_age_days", 0)

    def _format_age(self, days):
        """Human-readable age"""
        if days < 7:
            return f"{days} day{'s' if days != 1 else ''}"
        weeks = days // 7
        remaining = days % 7
        if remaining == 0:
            return f"{weeks} week{'s' if weeks != 1 else ''}"
        return f"{weeks} week{'s' if weeks != 1 else ''}, {remaining} day{'s' if remaining != 1 else ''}"

    def _get_milestone_key(self, batch):
        """Map batch type to milestone schedule"""
        bt = batch["type"]
        if bt == "broiler":
            return "poultry_broiler"
        elif bt == "layer":
            return "poultry_layer"
        elif bt == "tilapia":
            return "fish_tilapia"
        elif bt == "catfish":
            return "fish_catfish"
        elif bt == "pig":
            return "pig"
        return None

    def _get_next_milestone(self, batch):
        """Get the next upcoming milestone for a batch"""
        age = self._get_age_days(batch)
        key = self._get_milestone_key(batch)
        milestones = MILESTONE_MAP.get(key, [])

        for ms in milestones:
            if ms["day"] >= age:
                return ms
        return None

    def _find_batch(self, farm, batch_id):
        """Find a batch by ID"""
        for b in farm["batches"]:
            if b["id"] == batch_id:
                return b
        return None

    def _save(self, phone):
        """Save farm state to disk"""
        filepath = os.path.join(DATA_DIR, f"farm_{phone}.json")
        try:
            with open(filepath, "w") as f:
                json.dump(self.farms[phone], f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save farm state for {phone}: {e}")

    def _load_all(self):
        """Load all farm states from disk"""
        try:
            for filename in os.listdir(DATA_DIR):
                if filename.startswith("farm_") and filename.endswith(".json"):
                    phone = filename.replace("farm_", "").replace(".json", "")
                    filepath = os.path.join(DATA_DIR, filename)
                    with open(filepath, "r") as f:
                        self.farms[phone] = json.load(f)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Failed to load farm states: {e}")
