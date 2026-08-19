"""
FarmWise Engine — unified AI layer.
One module handles chat, vision (photos), and voice.
Groq primary (free), Gemini fallback.
Model names come from config — swap with an env var.
"""
import io
import base64
import logging
import requests
from config import (
    GROQ_API_KEY, GEMINI_API_KEY,
    CHAT_MODEL, VISION_MODEL, WHISPER_MODEL, GEMINI_MODEL,
    GROQ_CHAT_URL, GROQ_AUDIO_URL, GEMINI_URL_TEMPLATE,
    WHATSAPP_TOKEN,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# SYSTEM PROMPT
# ──────────────────────────────────────────────
BASE_PROMPT = """You are FarmWise, a friendly farm advisor for smallholder farmers in Ghana.

PERSONALITY: Warm, patient, practical. Like a trusted uncle who knows farming.
Keep responses SHORT — max 3-4 paragraphs. Farmers read on small phone screens.
Use GH₵ for prices. Reference Ghanaian brands, markets, conditions.
Respond in Twi if the farmer writes in Twi. Mix naturally.

RULES:
1. NEVER mention AI, artificial intelligence, algorithm, language model, or tech terms.
2. NEVER say "As an AI" — you are FarmWise, a farm advisor. Period.
3. Always give ACTIONABLE advice — what to do, what to buy, how much.
4. For disease: give diagnosis, treatment, dosage. Add "If no improvement in 2 days, contact a vet."
5. Use current Ghana prices. Feed bag = GH₵250-350. Day-old chick = GH₵15-25.
6. Answer ANY question naturally — farming, weather, business, whatever. You're approachable.
"""

PROMPTS = {
    "poultry": BASE_PROMPT + "\nSPECIALIZATION: Poultry (broilers + layers). Key: vaccination schedules, feed conversion 1.6-1.8:1, common diseases (ND, Gumboro, Coccidiosis, CRD, Fowl Pox).",
    "fish": BASE_PROMPT + "\nSPECIALIZATION: Fish (tilapia + catfish). Key: water quality (pH 6.5-8.5, DO >5mg/L), stocking density, feed protein 28-45% by stage.",
    "pig": BASE_PROMPT + "\nSPECIALIZATION: Pig. Key: ASF prevention (no cure/vaccine), breeds (Large White, Landrace, Ashanti Black), feed 16-20% protein.",
}


# ──────────────────────────────────────────────
# CHAT — any text message
# ──────────────────────────────────────────────
def get_ai_response(user_text, farm_type="poultry", language="en", history=None):
    system = PROMPTS.get(farm_type, PROMPTS["poultry"])
    msgs = [{"role": "system", "content": system}]
    if history:
        for h in history[-6:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": user_text})

    if GROQ_API_KEY:
        result = _groq_chat(msgs, CHAT_MODEL)
        if result:
            return result
    if GEMINI_API_KEY:
        return _gemini_chat(msgs, system)
    return "FarmWise is not configured yet. Please contact support."


# ──────────────────────────────────────────────
# VISION — analyze farm photos
# ──────────────────────────────────────────────
VISION_PROMPTS = {
    "poultry": "Count birds, estimate age by feathering, check health (droopy, discharge, swollen face). Note housing. Under 150 words. No AI/tech terms.",
    "fish": "Estimate count/size, identify species, check health (white patches, gasping), note water color. Under 150 words.",
    "pig": "Count pigs, estimate age/size, identify breed if possible, check skin/coat, note housing. Under 150 words.",
}

def analyze_photo(image_bytes=None, farm_type="poultry", media_id=None):
    """Analyze a farm photo. Downloads from WhatsApp if media_id provided."""
    if not image_bytes and media_id:
        image_bytes = _download_whatsapp_media(media_id)
    if not image_bytes:
        return "No image received. Please send a photo of your animals."

    prompt = "You are FarmWise, a farm advisor analyzing a photo. " + VISION_PROMPTS.get(farm_type, VISION_PROMPTS["poultry"])
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    mime = "image/png" if image_bytes[:4] == b'\x89PNG' else "image/jpeg"

    # Try Gemini first for vision (more reliable with base64)
    if GEMINI_API_KEY:
        result = _gemini_vision(b64, mime, prompt)
        if result:
            return result

    # Groq vision fallback (qwen supports image_url with data URI)
    if GROQ_API_KEY:
        result = _groq_vision(b64, mime, prompt)
        if result:
            return result

    return "Photo analysis isn't available right now. Describe what you see and I'll help."


# ──────────────────────────────────────────────
# VOICE — transcribe audio
# ──────────────────────────────────────────────
def transcribe_audio(audio_bytes=None, media_id=None):
    """Transcribe a voice note. Downloads from WhatsApp if media_id provided."""
    if not audio_bytes and media_id:
        audio_bytes = _download_whatsapp_media(media_id)
    if not audio_bytes:
        return None
    if not GROQ_API_KEY:
        return None

    try:
        resp = requests.post(
            GROQ_AUDIO_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": ("voice.ogg", io.BytesIO(audio_bytes), "audio/ogg")},
            data={
                "model": WHISPER_MODEL,
                "response_format": "json",
                "temperature": 0.0,
                "prompt": "Ghanaian farmer, poultry fish pig farming. Twi and English. Chicks layers broilers crates bags cedis fingerlings.",
            },
            timeout=30,
        )
        if resp.status_code == 200:
            text = resp.json().get("text", "").strip()
            logger.info(f"Transcribed: {text[:80]}")
            return text
        logger.error(f"Whisper error: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Transcription error: {e}")
    return None


# ──────────────────────────────────────────────
# INTERNAL — API calls
# ──────────────────────────────────────────────
def _groq_chat(messages, model):
    try:
        resp = requests.post(GROQ_CHAT_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 500, "temperature": 0.3},
            timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Groq chat error ({model}): {e}")
        return None

def _groq_vision(b64, mime, prompt):
    try:
        data_uri = f"data:{mime};base64,{b64}"
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]}]
        resp = requests.post(GROQ_CHAT_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": VISION_MODEL, "messages": msgs, "max_tokens": 300, "temperature": 0.2},
            timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Groq vision error: {e}")
        return None

def _gemini_chat(messages, system_prompt):
    try:
        url = GEMINI_URL_TEMPLATE.format(GEMINI_MODEL, GEMINI_API_KEY)
        contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
                    for m in messages if m["role"] != "system"]
        resp = requests.post(url, json={
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 500, "temperature": 0.3},
        }, timeout=30)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Gemini chat error: {e}")
        return "I'm having trouble right now. Please try again in a moment."

def _gemini_vision(b64, mime, prompt):
    try:
        url = GEMINI_URL_TEMPLATE.format(GEMINI_MODEL, GEMINI_API_KEY)
        resp = requests.post(url, json={
            "contents": [{"parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime, "data": b64}},
            ]}],
            "generationConfig": {"maxOutputTokens": 300, "temperature": 0.2},
        }, timeout=30)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Gemini vision error: {e}")
        return None

def _download_whatsapp_media(media_id):
    try:
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        resp = requests.get(f"https://graph.facebook.com/v21.0/{media_id}", headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        media_url = resp.json().get("url")
        if not media_url:
            return None
        resp = requests.get(media_url, headers=headers, timeout=30)
        return resp.content if resp.status_code == 200 else None
    except Exception as e:
        logger.error(f"Media download error: {e}")
        return None
