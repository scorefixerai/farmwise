"""
FarmWise Mortality Analysis
Detects spikes, trends, and abnormal patterns in daily mortality.
Flags issues before they become catastrophic.
"""

from datetime import datetime, timedelta, timezone
from collections import defaultdict


def analyze_mortality(daily_logs, batch_info=None):
    """
    Analyze mortality data for spikes and trends.

    daily_logs: list of dicts with at least {"mortality": int, "timestamp": str}
    batch_info: optional dict with {"type": str, "current_count": int, "initial_count": int}

    Returns dict with analysis and alert level.
    """
    if not daily_logs:
        return {"alert": None, "message": "No mortality data to analyze."}

    # Extract mortality values in chronological order
    mort_values = []
    for log in daily_logs:
        m = log.get("mortality", 0)
        if m and m > 0:
            mort_values.append(m)

    if not mort_values:
        return {"alert": "none", "message": "No mortalities recorded. Your flock looks healthy."}

    total_mort = sum(mort_values)
    days_with_mort = len(mort_values)
    avg_daily = total_mort / max(len(daily_logs), 1)

    # ── SPIKE DETECTION ──
    # A spike is when today's mortality is 3x the rolling average
    alert_level = "none"
    alert_message = ""

    if len(mort_values) >= 3:
        recent_3 = mort_values[-3:]
        older = mort_values[:-3] if len(mort_values) > 3 else mort_values[:1]
        avg_older = sum(older) / len(older) if older else 1
        latest = mort_values[-1]

        if latest >= avg_older * 3 and latest >= 5:
            alert_level = "critical"
            alert_message = (
                f"🔴 *MORTALITY SPIKE DETECTED*\n\n"
                f"Today: {latest} deaths\n"
                f"Your average was: {avg_older:.0f}/day\n"
                f"This is {latest/max(avg_older,1):.1f}x your normal rate.\n\n"
                f"Possible causes:\n"
            )
            if batch_info:
                alert_message += _get_likely_causes(batch_info.get("type", "poultry"), batch_info)
            else:
                alert_message += (
                    "• Disease outbreak (Newcastle, Gumboro, ASF)\n"
                    "• Water contamination\n"
                    "• Feed change or toxicity\n"
                    "• Heat stress\n"
                    "• Predator attack\n\n"
                )
            alert_message += "⚡ Check your animals NOW. Isolate any sick ones immediately."

        elif latest >= avg_older * 2 and latest >= 3:
            alert_level = "warning"
            alert_message = (
                f"⚠️ *Mortality increasing*\n\n"
                f"Today: {latest} deaths (average: {avg_older:.0f}/day)\n"
                f"Watch closely over the next 24 hours.\n"
                f"If it continues rising, isolate sick animals and check water/feed."
            )

    elif len(mort_values) >= 1 and mort_values[-1] >= 10:
        alert_level = "critical"
        alert_message = (
            f"🔴 *{mort_values[-1]} deaths recorded today*\n\n"
            f"This is significant. Possible causes:\n"
        )
        if batch_info:
            alert_message += _get_likely_causes(batch_info.get("type", "poultry"), batch_info)
        alert_message += "\n⚡ Check your animals NOW."

    # ── TREND ANALYSIS ──
    if len(mort_values) >= 5:
        trend_recent = sum(mort_values[-3:])
        trend_older = sum(mort_values[-5:-2]) if len(mort_values) >= 5 else sum(mort_values[:2])

        if trend_recent > trend_older * 1.5 and alert_level == "none":
            alert_level = "watch"
            alert_message = (
                f"📈 *Mortality trending up*\n\n"
                f"Last 3 entries: {trend_recent} deaths\n"
                f"Previous 3 entries: {trend_older} deaths\n"
                f"Not critical yet, but worth monitoring.\n"
                f"Review feed, water, and pen conditions."
            )

    # ── CUMULATIVE CHECK ──
    if batch_info and alert_level == "none":
        initial = batch_info.get("initial_count", 0)
        if initial > 0:
            mort_pct = (total_mort / initial) * 100
            if mort_pct > 10:
                alert_level = "warning"
                alert_message = (
                    f"⚠️ *High total mortality: {mort_pct:.1f}%*\n\n"
                    f"You've lost {total_mort} out of {initial} animals.\n"
                    f"Target is below 5%. Review your management:\n"
                    f"• Are vaccinations up to date?\n"
                    f"• Is the pen clean and dry?\n"
                    f"• Is the water fresh daily?\n"
                    f"• Is feed stored properly (no mold)?"
                )
            elif mort_pct > 5:
                alert_level = "watch"
                alert_message = (
                    f"📊 *Mortality at {mort_pct:.1f}%* ({total_mort} of {initial})\n"
                    f"Above the 5% target. Not critical, but room to improve.\n"
                    f"Focus on biosecurity and feed quality."
                )

    # ── NO ISSUES ──
    if alert_level == "none":
        mort_pct = 0
        if batch_info and batch_info.get("initial_count", 0) > 0:
            mort_pct = (total_mort / batch_info["initial_count"]) * 100
        alert_message = (
            f"✅ *Mortality looks normal*\n\n"
            f"Total deaths recorded: {total_mort}\n"
            f"Average: {avg_daily:.1f}/day over {len(daily_logs)} entries\n"
        )
        if mort_pct > 0:
            alert_message += f"Cumulative mortality: {mort_pct:.1f}%\n"
        alert_message += "Keep up the good work!"

    return {
        "alert": alert_level,
        "message": alert_message,
        "total_mortality": total_mort,
        "avg_daily": round(avg_daily, 1),
        "days_recorded": len(daily_logs),
        "latest": mort_values[-1] if mort_values else 0,
    }


def check_daily_mortality(farm_logger, farm_state_obj, phone):
    """
    Run mortality analysis using existing farm log data.
    Called when farmer types 'mortality' or automatically after logging deaths.
    """
    logs = farm_logger.logs.get(phone, [])
    if not logs:
        return "No data yet. Log your daily numbers: 'fed 3 bags, 200 eggs, 2 died'"

    farm = farm_state_obj.get_farm(phone)
    active_batches = [b for b in farm.get("batches", []) if b.get("active")]
    batch_info = None
    if active_batches:
        b = active_batches[0]
        batch_info = {
            "type": b["type"],
            "current_count": b["current_count"],
            "initial_count": b["initial_count"],
            "age_days": farm_state_obj._get_age_days(b),
        }

    # Filter logs that have mortality data
    mort_logs = [l for l in logs if l.get("mortality", 0) > 0 or l.get("mort", 0) > 0]
    # Normalize key names
    for l in mort_logs:
        if "mort" in l and "mortality" not in l:
            l["mortality"] = l["mort"]

    result = analyze_mortality(logs, batch_info)
    return result["message"]


def auto_check_after_log(log_entry, farm_logger, farm_state_obj, phone):
    """
    Automatically check mortality after a farmer logs deaths.
    Returns an alert message if mortality is abnormal, None otherwise.
    """
    mort = log_entry.get("mortality", 0) or log_entry.get("mort", 0)
    if mort < 3:
        return None  # Don't alert for 1-2 deaths — normal

    logs = farm_logger.logs.get(phone, [])
    farm = farm_state_obj.get_farm(phone)
    active_batches = [b for b in farm.get("batches", []) if b.get("active")]
    batch_info = None
    if active_batches:
        b = active_batches[0]
        batch_info = {
            "type": b["type"],
            "current_count": b["current_count"],
            "initial_count": b["initial_count"],
            "age_days": farm_state_obj._get_age_days(b),
        }

    result = analyze_mortality(logs, batch_info)

    if result["alert"] in ("critical", "warning"):
        return result["message"]
    return None


def _get_likely_causes(animal_type, batch_info=None):
    """Get age-specific likely causes of mortality"""
    age = batch_info.get("age_days", 0) if batch_info else 0

    if animal_type in ("broiler", "layer"):
        if age <= 7:
            return (
                "• Chilling (brooder too cold)\n"
                "• Navel infection (omphalitis)\n"
                "• Chick quality issue from hatchery\n"
                "• Dehydration — check water access\n\n"
            )
        elif age <= 21:
            return (
                "• Gumboro disease (white watery droppings?)\n"
                "• Newcastle disease (twisted neck, green droppings?)\n"
                "• Coccidiosis (bloody droppings?)\n"
                "• Brooder overheating\n\n"
            )
        elif age <= 42:
            return (
                "• Newcastle disease — is vaccination up to date?\n"
                "• Coccidiosis — check for bloody droppings\n"
                "• CRD — sneezing, swollen face?\n"
                "• Heat stress — provide ventilation\n"
                "• Feed toxicity — check for mold in feed\n\n"
            )
        else:
            return (
                "• Newcastle disease — booster due?\n"
                "• Chronic respiratory disease\n"
                "• Heat stress\n"
                "• Egg peritonitis (layers)\n"
                "• Predators\n\n"
            )

    elif animal_type in ("tilapia", "catfish"):
        return (
            "• Low dissolved oxygen — are fish gasping at surface?\n"
            "• Disease outbreak — check for white patches, lesions\n"
            "• Water quality — test pH, ammonia\n"
            "• Overcrowding\n"
            "• Poisoning — any chemicals used near pond?\n\n"
        )

    elif animal_type == "pig":
        return (
            "• ⚠️ African Swine Fever — red blotches, bloody diarrhea? REPORT IMMEDIATELY\n"
            "• Pneumonia — coughing, labored breathing?\n"
            "• Diarrhea (piglets) — dehydration\n"
            "• Heat stroke — provide shade and water\n"
            "• Internal parasites\n\n"
        )

    return (
        "• Disease outbreak\n"
        "• Water/feed contamination\n"
        "• Environmental stress\n"
        "• Predators\n\n"
    )
