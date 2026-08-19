"""
FarmWise Feed Calculator
Instant math — no API call needed.
Tells farmers exactly how many bags they need this week, what type of feed,
and what it will cost at current Ghana prices.
"""


# ──────────────────────────────────────────────
# FEED REQUIREMENT TABLES (grams per bird per day)
# Source: Cobb 500 / Lohmann Brown / Ranaan / industry standards
# ──────────────────────────────────────────────

BROILER_FEED = {
    # (min_day, max_day): (grams/bird/day, feed_type, protein_pct)
    (0, 7):    (15, "starter", 23),
    (8, 14):   (30, "starter", 23),
    (15, 21):  (55, "starter", 23),
    (22, 28):  (85, "grower", 20),
    (29, 35):  (110, "grower", 20),
    (36, 42):  (140, "finisher", 18),
    (43, 56):  (160, "finisher", 18),
}

LAYER_FEED = {
    (0, 7):     (12, "chick starter", 21),
    (8, 28):    (25, "chick starter", 21),
    (29, 56):   (45, "grower", 18),
    (57, 84):   (65, "grower", 18),
    (85, 112):  (80, "developer", 16),
    (113, 126): (90, "pre-layer", 17),
    (127, 504): (110, "layer", 17),
    (505, 999): (115, "layer", 17),
}

TILAPIA_FEED = {
    # grams per fish per day
    (0, 30):    (1.5, "fingerling", 45),
    (31, 60):   (3.0, "juvenile", 35),
    (61, 90):   (5.0, "grower", 32),
    (91, 120):  (7.0, "grower", 32),
    (121, 150): (8.5, "grower", 28),
    (151, 210): (10.0, "finisher", 28),
}

CATFISH_FEED = {
    (0, 30):    (2.0, "fingerling", 45),
    (31, 60):   (5.0, "juvenile", 40),
    (61, 90):   (10.0, "grower", 35),
    (91, 120):  (15.0, "grower", 32),
    (121, 180): (18.0, "finisher", 28),
}

PIG_FEED = {
    # grams per pig per day
    (0, 28):    (200, "creep", 22),
    (29, 56):   (500, "weaner", 20),
    (57, 84):   (1200, "grower", 16),
    (85, 112):  (2000, "grower", 16),
    (113, 140): (2800, "finisher", 14),
    (141, 180): (3200, "finisher", 14),
}

FEED_TABLES = {
    "broiler": BROILER_FEED,
    "layer": LAYER_FEED,
    "tilapia": TILAPIA_FEED,
    "catfish": CATFISH_FEED,
    "pig": PIG_FEED,
}

# Feed prices in Ghana (GH₵ per bag)
FEED_PRICES = {
    "poultry": {"bag_kg": 50, "price_range": (250, 350), "avg": 300},
    "fish": {"bag_kg": 15, "price_range": (300, 450), "avg": 375},
    "pig": {"bag_kg": 50, "price_range": (200, 300), "avg": 250},
}


def calculate_feed(batch_type, count, age_days, days_ahead=7):
    """
    Calculate feed requirements for a batch.

    Returns dict with:
    - daily_total_kg: total kg needed per day
    - weekly_total_kg: total kg for the period
    - bags_needed: number of bags to buy
    - feed_type: what type of feed to use
    - protein_pct: protein percentage needed
    - cost_estimate: estimated cost in GH₵
    - per_animal_g: grams per animal per day
    """
    table = FEED_TABLES.get(batch_type)
    if not table:
        return None

    # Find the right feed requirement for this age
    per_animal_g = 0
    feed_type = "unknown"
    protein_pct = 0

    for (min_d, max_d), (grams, ftype, protein) in table.items():
        if min_d <= age_days <= max_d:
            per_animal_g = grams
            feed_type = ftype
            protein_pct = protein
            break

    if per_animal_g == 0:
        # Age beyond our table — use the last entry
        last_entry = list(table.values())[-1]
        per_animal_g, feed_type, protein_pct = last_entry

    # Calculate totals
    daily_total_g = per_animal_g * count
    daily_total_kg = daily_total_g / 1000
    period_total_kg = daily_total_kg * days_ahead

    # Determine bag size and price
    farm_type_key = "poultry" if batch_type in ("broiler", "layer") else "fish" if batch_type in ("tilapia", "catfish") else "pig"
    price_info = FEED_PRICES.get(farm_type_key, FEED_PRICES["poultry"])
    bag_kg = price_info["bag_kg"]
    bags_needed = -(-int(period_total_kg) // bag_kg)  # ceiling division
    if bags_needed == 0:
        bags_needed = 1

    cost_low = bags_needed * price_info["price_range"][0]
    cost_high = bags_needed * price_info["price_range"][1]
    cost_avg = bags_needed * price_info["avg"]

    return {
        "per_animal_g": per_animal_g,
        "daily_total_kg": round(daily_total_kg, 1),
        "period_days": days_ahead,
        "period_total_kg": round(period_total_kg, 1),
        "bags_needed": bags_needed,
        "bag_size_kg": bag_kg,
        "feed_type": feed_type,
        "protein_pct": protein_pct,
        "cost_low": cost_low,
        "cost_high": cost_high,
        "cost_avg": cost_avg,
    }


def format_feed_response(calc, batch_type, count, age_days):
    """Format feed calculation as a WhatsApp message"""
    if not calc:
        return "I don't have feed data for that type of animal yet."

    age_weeks = age_days // 7
    age_str = f"{age_weeks} weeks" if age_weeks > 0 else f"{age_days} days"

    msg = f"🌾 *Feed calculation — {count} {batch_type}, {age_str} old*\n\n"
    msg += f"Feed type: {calc['feed_type']} ({calc['protein_pct']}% protein)\n"
    msg += f"Per animal: {calc['per_animal_g']}g/day\n"
    msg += f"Daily total: {calc['daily_total_kg']}kg\n\n"
    msg += f"📦 *This week ({calc['period_days']} days):*\n"
    msg += f"Total: {calc['period_total_kg']}kg\n"
    msg += f"Bags needed: {calc['bags_needed']} × {calc['bag_size_kg']}kg bags\n"
    msg += f"Cost: GH₵{calc['cost_low']:,} – GH₵{calc['cost_high']:,}\n"

    # Add advice based on age
    if batch_type == "broiler" and age_days >= 22 and age_days < 29:
        msg += f"\n💡 Switch from starter to grower feed this week if you haven't already."
    elif batch_type == "broiler" and age_days >= 36 and age_days < 43:
        msg += f"\n💡 Switch to finisher feed now. Lower protein saves you money."
    elif batch_type == "layer" and age_days >= 113 and age_days < 130:
        msg += f"\n💡 Switch to pre-layer or layer feed. Add calcium (oyster shell)."

    return msg


def calculate_feed_for_farm(farm_state_obj, phone):
    """Calculate total feed needs across all active batches"""
    farm = farm_state_obj.get_farm(phone)
    batches = [b for b in farm.get("batches", []) if b.get("active")]

    if not batches:
        return "No active batches. Register your animals first: 'I have 500 broilers, 2 weeks old'"

    msg = "🌾 *Weekly Feed Plan*\n\n"
    total_cost_low = 0
    total_cost_high = 0
    total_bags = 0

    for b in batches:
        age = farm_state_obj._get_age_days(b)
        calc = calculate_feed(b["type"], b["current_count"], age)
        if calc:
            msg += f"*Batch #{b['id']}:* {b['current_count']} {b['type']} ({farm_state_obj._format_age(age)})\n"
            msg += f"  {calc['feed_type']} — {calc['bags_needed']} bags — GH₵{calc['cost_low']:,}–{calc['cost_high']:,}\n\n"
            total_cost_low += calc["cost_low"]
            total_cost_high += calc["cost_high"]
            total_bags += calc["bags_needed"]

    msg += f"*Total this week:* {total_bags} bags\n"
    msg += f"*Total cost:* GH₵{total_cost_low:,} – GH₵{total_cost_high:,}"

    return msg
