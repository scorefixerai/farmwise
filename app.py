"""
FarmWise — WhatsApp Farm Management Agent
Lean server: config-driven, LLM-first, persistent sessions.
"""
import os
import json
import re
import logging
import requests
from datetime import datetime, timezone
from flask import Flask, request, jsonify

from config import (
    WHATSAPP_TOKEN, PHONE_NUMBER_ID, VERIFY_TOKEN,
    ADMIN_PHONES, DATA_DIR, WHATSAPP_API_URL,
)
from ai_engine import get_ai_response, analyze_photo, transcribe_audio
from farm_state import FarmState
from farm_log import FarmLogger
from invoicing import InvoiceManager
from protocols import get_biosecurity_checklist, check_inventory_anomaly, get_security_recommendations
from feed_calc import calculate_feed_for_farm
from mortality import check_daily_mortality, auto_check_after_log
from weather import get_weather_summary
from subscriptions import SubscriptionManager
from teams import TeamManager

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Persistent sessions ──
os.makedirs(DATA_DIR, exist_ok=True)
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")

def _load_sessions():
    try:
        with open(SESSIONS_FILE) as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}

def _save_sessions():
    try:
        with open(SESSIONS_FILE, "w") as f: json.dump(sessions, f, default=str)
    except Exception as e: logger.error(f"Session save error: {e}")

sessions = _load_sessions()

# ── Modules ──
farm_state = FarmState()
farm_logger = FarmLogger()
invoice_mgr = InvoiceManager()
sub_mgr = SubscriptionManager()
team_mgr = TeamManager()


# ──────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────
@app.route("/")
def index():
    return jsonify({"status": "running", "service": "FarmWise", "active_users": len(sessions)})

@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge", ""), 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return jsonify({"status": "no messages"}), 200

        msg = messages[0]
        sender = msg["from"]
        msg_type = msg["type"]
        ts = datetime.now(timezone.utc).isoformat()

        # ── Get or create session ──
        if sender not in sessions:
            sessions[sender] = {"farm_type": None, "onboarded": False, "language": "en", "history": [], "location": "kumasi"}
            _save_sessions()
            _send_onboarding(sender)
            return jsonify({"status": "onboarding"}), 200

        session = sessions[sender]

        # ── Extract message content ──
        user_text = ""
        if msg_type == "text":
            user_text = msg["text"]["body"]
        elif msg_type == "audio":
            send(sender, "🎙️ Processing your voice note...")
            user_text = transcribe_audio(media_id=msg["audio"]["id"]) or ""
            if not user_text:
                send(sender, "I couldn't understand that voice note. Please try again or type your message.")
                return jsonify({"status": "voice failed"}), 200
        elif msg_type == "image":
            send(sender, "📸 Analyzing your photo...")
            result = analyze_photo(farm_type=session.get("farm_type", "poultry"), media_id=msg["image"]["id"])
            send(sender, result)
            return jsonify({"status": "photo"}), 200
        elif msg_type == "interactive":
            interactive = msg["interactive"]
            if interactive["type"] == "button_reply":
                user_text = interactive["button_reply"]["title"]
            elif interactive["type"] == "list_reply":
                user_text = interactive["list_reply"]["title"]
        else:
            return jsonify({"status": "unsupported type"}), 200

        if not user_text:
            return jsonify({"status": "empty"}), 200

        # ── Onboarding ──
        if not session["onboarded"]:
            _handle_onboarding(sender, user_text, session)
            return jsonify({"status": "onboarding"}), 200

        # ── Process message ──
        logger.info(f"Message from {sender}: {user_text[:100]}")
        text_lower = user_text.lower().strip()

        # Subscription commands (always allowed)
        if text_lower in ("subscribe", "pay", "upgrade", "renew"):
            send(sender, sub_mgr.create_payment_link(sender))
        elif text_lower in ("account", "subscription", "plan"):
            send(sender, sub_mgr.get_status(sender))
        else:
            # Check access
            has_access, block_msg = sub_mgr.check_access(sender)
            if not has_access:
                send(sender, block_msg)
            else:
                if block_msg:  # trial warning
                    send(sender, block_msg)
                _route(sender, user_text, text_lower, session, ts)

        # Save history
        session["history"].append({"role": "user", "content": user_text, "ts": ts})
        if len(session["history"]) > 20:
            session["history"] = session["history"][-20:]
        _save_sessions()

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
    return jsonify({"status": "ok"}), 200


@app.route("/payment/webhook", methods=["POST"])
def payment_webhook():
    try:
        data = request.get_json()
        if sub_mgr.handle_webhook(data):
            phone = data.get("data", {}).get("metadata", {}).get("phone", "")
            if phone:
                send(phone, sub_mgr.get_status(phone))
    except Exception as e:
        logger.error(f"Payment webhook error: {e}")
    return jsonify({"status": "ok"}), 200

@app.route("/payment/callback")
def payment_callback():
    return "<h1>Payment received! Go back to WhatsApp — FarmWise is active.</h1>", 200


# ──────────────────────────────────────────────
# MESSAGE ROUTER — keyword commands + LLM fallback
# ──────────────────────────────────────────────
def _route(sender, text, tl, session, ts):
    ft = session["farm_type"]

    # ── Instant commands (no API call) ──
    COMMANDS = {
        ("farm", "my farm", "status", "batches"): lambda: farm_state.get_farm_summary(sender),
        ("advice", "today", "daily", "reminders"): lambda: farm_state.get_daily_advice(sender) or "No milestones due today. Everything on track! 👍",
        ("feed", "feed plan", "bags"): lambda: calculate_feed_for_farm(farm_state, sender),
        ("weather", "rain", "forecast"): lambda: get_weather_summary(session.get("location", "kumasi"), ft),
        ("checklist", "daily checklist", "protocol"): lambda: get_biosecurity_checklist(ft, "daily"),
        ("weekly checklist",): lambda: get_biosecurity_checklist(ft, "weekly"),
        ("monthly checklist",): lambda: get_biosecurity_checklist(ft, "monthly"),
        ("rules", "biosecurity rules", "prevention"): lambda: get_biosecurity_checklist(ft, "rules"),
        ("security", "theft", "anti-theft"): lambda: get_security_recommendations(ft),
        ("count check", "inventory check"): lambda: check_inventory_anomaly(farm_state, sender) or "✅ Inventory consistent.",
        ("invoices", "unpaid", "outstanding"): lambda: invoice_mgr.get_outstanding(sender),
        ("revenue", "sales", "income"): lambda: invoice_mgr.get_revenue_summary(sender),
        ("mortality", "deaths", "death report"): lambda: check_daily_mortality(farm_logger, farm_state, sender),
        ("summary", "weekly report"): lambda: farm_logger.get_weekly_summary(sender),
        ("team", "my team", "workers", "staff"): lambda: team_mgr.get_team_summary(sender),
        ("tasks", "pending tasks", "pending"): lambda: team_mgr.get_pending_tasks(sender),
    }

    for keys, handler in COMMANDS.items():
        if tl in keys:
            send(sender, handler())
            return

    # ── Parameterized commands ──
    if tl.startswith("weather "):
        loc = tl.replace("weather ", "").strip()
        session["location"] = loc
        send(sender, get_weather_summary(loc, ft))

    elif tl.startswith("paid "):
        m = re.search(r'(FW-\d{4})', text, re.IGNORECASE)
        send(sender, invoice_mgr.mark_paid(sender, m.group(1).upper()) if m else "Which invoice? e.g. 'paid FW-0001'")

    elif tl.startswith("add worker ") or tl.startswith("add manager "):
        parsed = team_mgr.parse_add_member(text)
        send(sender, team_mgr.add_member(sender, parsed["name"], parsed["phone"], parsed["role"]) if parsed else "Try: 'add worker Kwame 0241234567'")

    elif tl.startswith("assign "):
        parsed = team_mgr.parse_assign(text)
        send(sender, team_mgr.assign_task(sender, parsed["name"], parsed["task"], send_func=send) if parsed else "Try: 'assign Kwame vaccinate batch 1 today'")

    elif tl.startswith("remove "):
        send(sender, team_mgr.remove_member(sender, text[7:].strip()))

    elif tl == "done":
        result = team_mgr.complete_task(sender)
        send(sender, result["message"])
        if result.get("success") and result.get("owner_phone"):
            send(result["owner_phone"], f"✅ {result['worker_name']} completed: {result['task']}")

    elif tl in ("help", "menu", "commands"):
        send(sender,
            "📋 *FarmWise Commands*\n\n"
            "*Farm:* farm · advice · feed · summary\n"
            "*Safety:* weather · checklist · security · mortality\n"
            "*Money:* invoices · revenue · 'sold X to Y for Z'\n"
            "*Team:* team · 'add worker Name Phone' · 'assign Name task' · tasks\n"
            "*Account:* subscribe · account\n\n"
            "Or just ask me anything! Photos and voice notes work too."
        )

    # ── Everything else → LLM ──
    else:
        context = farm_state.get_context_for_llm(sender)
        enhanced = context + text if context else text
        response = get_ai_response(enhanced, ft, session["language"], session["history"][-6:])
        send(sender, response)

        # Silent background processing
        if farm_state.is_registration(text):
            p = farm_state.parse_registration(text, ft)
            if p["count"] and p["batch_type"]:
                send(sender, farm_state.add_batch(sender, p["batch_type"], p["count"], start_age_days=p["age_days"], breed=p["breed"]))

        elif _is_farm_log(text):
            send(sender, farm_logger.log_entry(sender, text, ts))
            parsed = farm_logger._parse_entry(text)
            batches = [b for b in farm_state.get_farm(sender).get("batches", []) if b.get("active")]
            if batches and (parsed.get("mortality", 0) > 0 or parsed.get("sold_quantity", 0) > 0):
                farm_state.update_count(sender, batches[0]["id"], died=parsed.get("mortality", 0), sold=parsed.get("sold_quantity", 0))
            if parsed.get("mortality", 0) >= 3:
                alert = auto_check_after_log(parsed, farm_logger, farm_state, sender)
                if alert:
                    send(sender, alert)

        elif invoice_mgr.is_sale_with_invoice(text):
            ps = invoice_mgr.parse_sale(text, ft)
            if ps["items"]:
                inv = invoice_mgr.create_invoice(sender, ps["items"], buyer_name=ps["buyer_name"], buyer_phone=ps["buyer_phone"])
                send(sender, invoice_mgr.format_invoice_message(inv))


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def send(phone, text):
    """Send a WhatsApp text message"""
    if not text or not WHATSAPP_TOKEN:
        return
    try:
        requests.post(WHATSAPP_API_URL,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": text[:4096]}},
            timeout=10)
    except Exception as e:
        logger.error(f"Send error: {e}")

def _send_onboarding(phone):
    """Send welcome message with farm type buttons"""
    try:
        requests.post(WHATSAPP_API_URL,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"},
            json={
                "messaging_product": "whatsapp", "to": phone, "type": "interactive",
                "interactive": {
                    "type": "button", "body": {
                        "text": "Welcome to FarmWise! 🌾\n\nI'm your farm advisor. I help you track your animals, prevent disease, optimize feed, and grow your profits.\n\nWhat type of farm do you run?"
                    },
                    "action": {"buttons": [
                        {"type": "reply", "reply": {"id": "poultry", "title": "Poultry"}},
                        {"type": "reply", "reply": {"id": "fish", "title": "Fish"}},
                        {"type": "reply", "reply": {"id": "pig", "title": "Pig"}},
                    ]}
                }
            }, timeout=10)
    except Exception as e:
        logger.error(f"Onboarding error: {e}")
        send(phone, "Welcome to FarmWise! 🌾 What type of farm do you run? Reply: Poultry, Fish, or Pig")

def _handle_onboarding(phone, text, session):
    tl = text.lower().strip()
    if tl in ("poultry", "fish", "pig"):
        session["farm_type"] = tl
        session["onboarded"] = True
        _save_sessions()
        send(phone,
            f"Great! I'm your {tl} farm advisor.\n\n"
            f"You can:\n"
            f"• Register animals: 'I bought 500 broiler chicks'\n"
            f"• Log daily data: 'fed 3 bags, 200 eggs, 2 died'\n"
            f"• Send a photo for counting & health check\n"
            f"• Send voice notes in English or Twi\n"
            f"• Type 'help' for all commands\n\n"
            f"Start by telling me about your farm!")
    else:
        send(phone, "Please choose your farm type: Poultry, Fish, or Pig")

def _is_farm_log(text):
    """Detect daily log entries"""
    tl = text.lower()
    triggers = ["fed ", "eggs", "collected", "harvested", "mortality", " died", " dead", "bags", "crates"]
    has_number = bool(re.search(r'\d+', tl))
    has_trigger = any(t in tl for t in triggers)
    not_question = "?" not in text and not tl.startswith(("how", "what", "why", "when", "where", "should", "can"))
    return has_number and has_trigger and not_question


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
