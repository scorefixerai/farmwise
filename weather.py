"""
FarmWise Weather Alerts
Uses Open-Meteo API (free, no key needed, no rate limits).
Gives farm-specific weather advice — not just temperature,
but what the weather means for your animals.
"""

import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Ghana region coordinates
GHANA_REGIONS = {
    "kumasi":       (6.6885, -1.6244),
    "accra":        (5.6037, -0.1870),
    "tamale":       (9.4008, -0.8393),
    "cape coast":   (5.1036, -1.2466),
    "takoradi":     (4.8846, -1.7554),
    "sunyani":      (7.3349, -2.3268),
    "ho":           (6.6000, 0.4700),
    "koforidua":    (6.0941, -0.2573),
    "wa":           (10.0601, -2.5099),
    "bolgatanga":   (10.7863, -0.8513),
    "dormaa":       (7.3500, -2.7833),
    "techiman":     (7.5833, -1.9333),
    "ejura":        (7.3833, -1.3667),
    "bekwai":       (6.4571, -1.5821),
    "asutsuare":    (6.1833, 0.0500),
    # Default for unspecified
    "ghana":        (7.9465, -1.0232),
}


def get_weather(location="kumasi"):
    """
    Get current weather and 2-day forecast for a location.
    Uses Open-Meteo API — completely free, no key needed.
    """
    location = location.lower().strip()
    coords = GHANA_REGIONS.get(location, GHANA_REGIONS["ghana"])

    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={coords[0]}&longitude={coords[1]}"
            f"&current=temperature_2m,relative_humidity_2m,rain,wind_speed_10m"
            f"&daily=temperature_2m_max,temperature_2m_min,rain_sum,uv_index_max"
            f"&timezone=Africa/Accra"
            f"&forecast_days=3"
        )

        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        current = data.get("current", {})
        daily = data.get("daily", {})

        return {
            "location": location.title(),
            "current": {
                "temp": current.get("temperature_2m", 0),
                "humidity": current.get("relative_humidity_2m", 0),
                "rain": current.get("rain", 0),
                "wind": current.get("wind_speed_10m", 0),
            },
            "forecast": {
                "dates": daily.get("time", []),
                "max_temps": daily.get("temperature_2m_max", []),
                "min_temps": daily.get("temperature_2m_min", []),
                "rain": daily.get("rain_sum", []),
                "uv": daily.get("uv_index_max", []),
            },
            "success": True,
        }

    except Exception as e:
        logger.error(f"Weather API error: {e}")
        return {"success": False, "error": str(e)}


def format_weather_for_farmer(weather_data, farm_type="poultry"):
    """
    Format weather data as farm-specific advice.
    Not just "it's 32°C" but "your birds are at risk of heat stress."
    """
    if not weather_data.get("success"):
        return (
            "I couldn't check the weather right now. "
            "Try again in a few minutes, or check your local radio."
        )

    c = weather_data["current"]
    f = weather_data["forecast"]
    loc = weather_data["location"]

    msg = f"🌤️ *Weather — {loc}*\n\n"
    msg += f"Now: {c['temp']}°C, {c['humidity']}% humidity"
    if c["rain"] > 0:
        msg += f", raining ({c['rain']}mm)"
    if c["wind"] > 20:
        msg += f", windy ({c['wind']}km/h)"
    msg += "\n\n"

    # Forecast
    if f["dates"]:
        msg += "*Next 3 days:*\n"
        day_names = ["Today", "Tomorrow", "Day after"]
        for i in range(min(3, len(f["dates"]))):
            rain = f["rain"][i] if i < len(f["rain"]) else 0
            max_t = f["max_temps"][i] if i < len(f["max_temps"]) else 0
            min_t = f["min_temps"][i] if i < len(f["min_temps"]) else 0
            rain_icon = "🌧️" if rain > 5 else "🌦️" if rain > 0 else "☀️"
            day_name = day_names[i] if i < len(day_names) else f["dates"][i]
            msg += f"{rain_icon} {day_name}: {min_t:.0f}–{max_t:.0f}°C"
            if rain > 0:
                msg += f", {rain:.0f}mm rain"
            msg += "\n"

    msg += "\n"

    # ── FARM-SPECIFIC ALERTS ──
    alerts = _get_farm_alerts(c, f, farm_type)
    if alerts:
        msg += "*What this means for your farm:*\n"
        for alert in alerts:
            msg += f"• {alert}\n"

    return msg


def _get_farm_alerts(current, forecast, farm_type):
    """Generate farm-specific weather alerts"""
    alerts = []
    temp = current["temp"]
    humidity = current["humidity"]
    rain_today = forecast["rain"][0] if forecast.get("rain") else 0
    rain_tomorrow = forecast["rain"][1] if len(forecast.get("rain", [])) > 1 else 0
    max_temp_today = forecast["max_temps"][0] if forecast.get("max_temps") else temp

    if farm_type in ("poultry", "broiler", "layer"):
        # Heat stress
        if max_temp_today > 35:
            alerts.append("🔴 HEAT STRESS RISK — provide extra water, increase ventilation, reduce stocking. Birds die above 40°C")
        elif max_temp_today > 32:
            alerts.append("⚠️ Hot day ahead — ensure good ventilation and plenty of clean water")

        # Cold (for chicks)
        if temp < 20:
            alerts.append("❄️ Cool night — check brooder temperature for young chicks (should be 30-33°C)")

        # Rain
        if rain_tomorrow > 10:
            alerts.append(f"🌧️ Heavy rain tomorrow ({rain_tomorrow:.0f}mm) — check pen roof for leaks, cover feed store")
        elif rain_tomorrow > 0:
            alerts.append("🌦️ Some rain expected — make sure litter stays dry")

        # Humidity
        if humidity > 85:
            alerts.append("💧 Very high humidity — wet litter increases Coccidiosis risk. Add dry shavings")

    elif farm_type in ("fish", "tilapia", "catfish"):
        if max_temp_today > 35:
            alerts.append("🔴 Very hot — pond oxygen drops in heat. Reduce feeding, add aeration if possible")
        if rain_tomorrow > 20:
            alerts.append(f"🌧️ Heavy rain tomorrow ({rain_tomorrow:.0f}mm) — watch for flooding, check pond banks and overflow")
        if temp < 22:
            alerts.append("❄️ Cool temperatures — fish feeding and growth slow below 22°C, reduce feed amount")

    elif farm_type == "pig":
        if max_temp_today > 35:
            alerts.append("🔴 HEAT STRESS — pigs cannot sweat. Provide shade, mud wallow, and spray water on them")
        elif max_temp_today > 32:
            alerts.append("⚠️ Hot day — ensure pigs have shade and access to water for cooling")
        if rain_tomorrow > 15:
            alerts.append(f"🌧️ Heavy rain tomorrow — check pen drainage, pigs in flooded pens get sick")
        if temp < 18:
            alerts.append("❄️ Cool night — piglets need warmth. Check creep area heating")

    if not alerts:
        alerts.append("Weather looks fine for your farm today")

    return alerts


def get_weather_summary(location="kumasi", farm_type="poultry"):
    """One-step: fetch weather + format for farmer"""
    data = get_weather(location)
    return format_weather_for_farmer(data, farm_type)
