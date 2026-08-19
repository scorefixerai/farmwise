"""
FarmWise Security & Biosecurity Protocols
1. Disease prevention — scheduled checklists and reminders
2. Theft detection — inventory reconciliation, unusual count alerts
3. Farm security — practical anti-theft measures
"""

import logging
logger = logging.getLogger(__name__)


POULTRY_BIOSECURITY = {
    "daily": [
        "Check water drinkers — clean and refill with fresh water",
        "Observe birds for 5 minutes — look for droopy, isolated, or sneezing birds",
        "Remove any dead birds immediately — do NOT leave in the pen",
        "Check feed troughs — birds should finish feed within 2-3 hours",
        "Footbath at pen entrance — change disinfectant (Izal/Dettol) daily",
    ],
    "weekly": [
        "Clean and disinfect drinkers and feeders with Izal solution",
        "Check litter — if wet or caked, add dry shavings on top",
        "Weigh a sample of 10 birds — compare to target weight for age",
        "Check for external parasites (lice, mites) — inspect under wings",
        "Inspect pen for holes or gaps where rodents or wild birds can enter",
    ],
    "monthly": [
        "Deep clean the pen — remove all old litter, wash with disinfectant",
        "Deworm entire flock with Piperazine (in water)",
        "Check all vaccination records — any boosters due?",
        "Inspect roof for leaks — wet litter causes disease",
        "Review mortality records — is the rate below 5%?",
    ],
    "rules": [
        "No visitors in the pen without clean boots and clothes",
        "Wash hands with soap before and after entering each pen",
        "Keep a visitor logbook — record who enters and when",
        "Do NOT allow other poultry farmers to enter your pen",
        "New birds must be quarantined for 14 days before mixing",
        "Do not share equipment (feeders, drinkers) with other farms",
        "Dead birds: burn or bury deep (1 meter) with lime",
        "Keep wild birds out — cover pen openings with wire mesh",
        "Store feed in dry, rodent-proof containers",
        "Keep a clean zone around the pen — no rubbish or standing water within 5 meters",
    ],
}

FISH_BIOSECURITY = {
    "daily": [
        "Check water color — clear/light green is good, dark green/brown is concern",
        "Observe feeding — fish should eat within 15-20 minutes",
        "Remove any dead fish immediately",
        "Check pump/aerator if using one — must run 24 hours",
        "Monitor water level — top up if dropping",
    ],
    "weekly": [
        "Test water quality if you have a kit (pH 6.5-8.5, ammonia < 0.5mg/L)",
        "Partial water change — 10-20% of pond volume",
        "Check for predators — birds, snakes, frogs near the pond",
        "Inspect pond banks for erosion or leaks",
        "Sample fish for weight — are they on track?",
    ],
    "monthly": [
        "Full water quality assessment",
        "Check stocking density — adjust if overcrowded",
        "Clean inlet/outlet screens",
        "Review feed conversion ratio",
        "Inspect pond bottom — excessive sludge reduces oxygen",
    ],
    "rules": [
        "Never introduce fish from unknown sources without quarantine",
        "Quarantine new fish for 7-14 days in a separate tank/pond",
        "Do not share nets or equipment between ponds without disinfecting",
        "Keep livestock away from fish ponds — runoff causes water issues",
        "Do not use pesticides near fish ponds",
        "Control vegetation around pond edges to reduce predator hiding spots",
        "Install bird netting over ponds if bird predation is a problem",
    ],
}

PIG_BIOSECURITY = {
    "daily": [
        "Clean water troughs — pigs need fresh water always",
        "Remove uneaten feed — rotting feed causes disease",
        "Check all pigs for illness — not eating, coughing, skin patches",
        "Clean pen floor — remove waste, ensure drainage working",
        "Check for unusual visitors or disturbances around the pen",
    ],
    "weekly": [
        "Deep clean pen with disinfectant (Izal solution)",
        "Check fence/pen integrity — pigs can break weak structures",
        "Inspect skin of all pigs — look for mange, wounds, parasites",
        "Weigh growing pigs if possible",
        "Trim hooves if needed on mature pigs",
    ],
    "monthly": [
        "Deworm all pigs with Ivermectin",
        "Spray pen for external parasites",
        "Review records — growth rate, feed consumption, health events",
        "Check boar condition if breeding",
        "Clean and repair wallowing area",
    ],
    "rules": [
        "CRITICAL: African Swine Fever — NO visitors from other pig farms",
        "Never feed kitchen waste/swill without boiling first (ASF risk)",
        "Wash boots in disinfectant footbath before entering pen",
        "Quarantine new pigs for 21 days before mixing",
        "Do not share transport vehicles without thorough disinfection",
        "Keep a visitor logbook — record who enters and when",
        "Separate sick pigs immediately — use an isolation pen",
        "Dead pigs: report to vet services, burn or bury with lime",
        "Control rodents — they spread diseases",
        "Fence the entire pig area — keep stray animals out",
    ],
}

BIOSECURITY_MAP = {
    "poultry": POULTRY_BIOSECURITY,
    "fish": FISH_BIOSECURITY,
    "pig": PIG_BIOSECURITY,
}


def get_biosecurity_checklist(farm_type, period="daily"):
    """Get the biosecurity checklist for a farm type and period"""
    protocols = BIOSECURITY_MAP.get(farm_type, POULTRY_BIOSECURITY)
    items = protocols.get(period, [])
    if not items:
        return f"No {period} checklist available for {farm_type} farms."

    emoji_map = {"daily": "📋", "weekly": "📅", "monthly": "📆", "rules": "🔒"}
    title_map = {
        "daily": "Daily checklist",
        "weekly": "Weekly checklist",
        "monthly": "Monthly checklist",
        "rules": "Biosecurity rules (always follow these)",
    }
    emoji = emoji_map.get(period, "📋")
    msg = f"{emoji} *{title_map.get(period, period)} — {farm_type.capitalize()} Farm*\n\n"
    for i, item in enumerate(items, 1):
        msg += f"{i}. {item}\n"
    return msg


def check_inventory_anomaly(farm_state_obj, phone):
    """
    Detect suspicious inventory changes that might indicate theft.
    Flags when animals are unaccounted for (not recorded as dead or sold).
    """
    farm = farm_state_obj.get_farm(phone)
    batches = [b for b in farm.get("batches", []) if b.get("active")]
    alerts = []

    for b in batches:
        initial = b["initial_count"]
        current = b["current_count"]
        died = b["mortality_total"]
        sold = b["sold_total"]
        added = b.get("added_total", 0)

        expected = initial - died - sold + added
        discrepancy = expected - current

        if discrepancy > 0 and discrepancy > initial * 0.02:
            alerts.append({
                "batch_id": b["id"],
                "batch_type": b["type"],
                "expected": expected,
                "actual": current,
                "missing": discrepancy,
                "pct": (discrepancy / initial * 100),
            })

    if not alerts:
        return None

    msg = "🔴 *Inventory Alert*\n\n"
    for a in alerts:
        msg += (
            f"Batch #{a['batch_id']} ({a['batch_type']}):\n"
            f"Expected: {a['expected']} | Actual: {a['actual']}\n"
            f"⚠️ {a['missing']} animals unaccounted for ({a['pct']:.1f}%)\n\n"
        )
    msg += (
        "What to do:\n"
        "1. Do a physical count — walk through and count all animals\n"
        "2. Check for dead animals you may have missed\n"
        "3. Ask workers if any animals were moved or sold\n"
        "4. If theft is confirmed, report to local police\n"
    )
    return msg


def get_security_recommendations(farm_type):
    """Practical anti-theft measures for the farm"""
    common = [
        "Install a padlock on all pen/pond gates — lock every night",
        "Keep a logbook of everyone who enters the farm",
        "Do a physical head count every morning and evening",
        "Install solar-powered security lights around the farm",
        "Keep farm records — documentation helps with police reports",
        "Build good relationships with neighbors — they notice strangers",
        "Consider a guard dog for night security",
        "Never tell strangers how many animals you have or when you sell",
    ]
    specific = {
        "poultry": [
            "Use wire mesh on all windows and openings",
            "Number your crates — know how many go out and come back",
            "Mark your birds with colored leg bands if possible",
            "Count birds at feeding time — they all come to eat",
            "Lock feed store separately — feed theft is also common",
        ],
        "fish": [
            "Fence the entire pond area with at least 1.5m fencing",
            "Install a gate with a lock on the access path to ponds",
            "Consider a caretaker who lives on-site near the ponds",
            "Harvest only during daytime with witnesses",
            "Keep harvest records with buyer names and quantities",
        ],
        "pig": [
            "Reinforce pen walls — pigs and thieves can break weak structures",
            "Mark/tag your pigs (ear tags or ear notching)",
            "Take photos of each pig for identification",
            "Lock all gates at night",
            "Know your pig market sellers — report suspicious cheap pig offers",
        ],
    }
    type_specific = specific.get(farm_type, [])

    msg = "🔒 *Security Recommendations*\n\n*General:*\n"
    for i, item in enumerate(common, 1):
        msg += f"{i}. {item}\n"
    msg += f"\n*{farm_type.capitalize()}-specific:*\n"
    for i, item in enumerate(type_specific, 1):
        msg += f"{i}. {item}\n"
    return msg
