"""
FarmWise Configuration — single source of truth.
Every setting comes from environment variables with sensible defaults.
Change models, prices, limits, and behavior without touching code.
"""
import os

# ── AI Models (change via env var to swap instantly) ──
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CHAT_MODEL = os.getenv("CHAT_MODEL", "openai/gpt-oss-20b")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen/qwen3.6-27b")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-large-v3-turbo")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# ── WhatsApp ──
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "farmwise_verify_2024")

# ── Subscription ──
FREE_TRIAL_MESSAGES = int(os.getenv("FREE_TRIAL_MESSAGES", "50"))
MONTHLY_PRICE_GHS = int(os.getenv("MONTHLY_PRICE_GHS", "30"))
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")

# ── Admin (comma-separated phone numbers, always unlimited access) ──
ADMIN_PHONES = [p.strip() for p in os.getenv("ADMIN_PHONES", "").split(",") if p.strip()]

# ── Storage ──
DATA_DIR = os.getenv("DATA_DIR", "./farm_data")
BASE_URL = os.getenv("BASE_URL", "https://farmwise-bot.onrender.com")

# ── API URLs (shouldn't need changing) ──
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}"
WHATSAPP_API_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
