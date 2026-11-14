#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NPZ Edge TTS + Gemini Proxy Server
===================================
NPZ Movie Recap Studio App ထဲကနေ ဖုန်း Chrome မှာပါ Thiha / Nilar
အသံအစစ် (MP3) ရအောင် + Browser ကနေ Google Gemini ကို တိုက်ရိုက်ခေါ်လို့
မရလို့ (Failed to fetch) Gemini ကို Server ဘက်ကနေ ခေါ်ပေးတဲ့ ကြားခံ Server လေး။

API:
  GET  /             -> စမ်းဖို့ စာမျက်နှာ
  GET  /health       -> {"ok": true}
  POST /tts          -> JSON {text, voice, rate} -> MP3 bytes
  GET  /tts?text=...&voice=...&rate=... -> MP3 bytes (browser မှာ စမ်းဖို့)
  POST /gemini-test  -> JSON {key, model} -> {ok, status, text}
  POST /gemini-srt   -> JSON {key, model, audio_base64, language, narration_style, chunk_start_seconds}
                       -> {ok, status, srt, raw_text}
  POST /eleven-tts   -> JSON {key, voice_id, model, text, stability, similarity_boost} -> MP3 bytes
  POST /eleven-voices -> JSON {key} -> {ok, voices: [{voice_id, name, labels}]}

အသံများ:
  my-MM-ThihaNeural (အမျိုးသား) / my-MM-NilarNeural (အမျိုးသမီး)
TTS အတွက် Key မလိုပါ — edge-tts က Microsoft Edge TTS ကို တိုက်ရိုက်သုံးပါတယ်။
Gemini အတွက် NPZ ရဲ့ကိုယ်ပိုင် API Key ကို App ထဲကနေ တစ်ခါသုံးအဖြစ် ပို့ရမယ် —
Server က Key ကို ဘယ်နေရာမှ မသိမ်းဘူး, Google ကို ခေါ်ပြီးတာနဲ့ မေ့လိုက်တယ်။
ElevenLabs အတွက်လည်း အတူတူပဲ — NPZ ရဲ့ကိုယ်ပိုင် ElevenLabs API Key ကို
App ထဲကနေ တစ်ခါသုံးအဖြစ် ပို့ရမယ်, Server က Key ကို ဘယ်နေရာမှ မသိမ်းဘူး။
ElevenLabs v4 model က Burmese (my) ထောက်ပံ့တယ် — အသံကောင်းမကောင်း စမ်းကြည့်ရမယ်။
Free tier: တစ်လ 10,000 characters (~10 မိနစ်), commercial use မရ။

Run (local):
  pip install -r requirements.txt
  uvicorn server:app --host 0.0.0.0 --port 8000
"""
import os
import re
import tempfile

import edge_tts
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, field_validator

app = FastAPI(title="NPZ Edge TTS + Gemini Proxy Server")

# NPZ ရဲ့ App (muse.ai) ကနေ ခေါ်လို့ရအောင် CORS အကုန်ဖွင့်ထားတယ်။
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

VOICES = {
    # key တွေက App / client က ပို့တဲ့ voice နာမည်တွေ; value ကတော့ Edge TTS ကို
    # ပေးရမယ့် voice နာမည် အစစ် ဖြစ်ရမယ် (display label ပေးလို့ မရဘူး —
    # "Nilar (အမျိုးသမီး)" လို label ပေးမိရင် Edge က Invalid voice ဆိုပြီး
    # 502 ပြန်တယ်, ဒါကြောင့် canonical နာမည်ကို သူ့အတိုင်း ပြန်ပေးတယ်)
    "my-MM-ThihaNeural": "my-MM-ThihaNeural",
    "my-MM-NilarNeural": "my-MM-NilarNeural",
    "male": "my-MM-ThihaNeural",
    "female": "my-MM-NilarNeural",
    "thiha": "my-MM-ThihaNeural",
    "nilar": "my-MM-NilarNeural",
}

GEMINI_MODELS = {
    "gemini-3.8-flash",
    "gemini-3.8-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
}

ELEVEN_MODELS = {
    "eleven_v4_turbo",
    "eleven_v4",
    "eleven_multilingual_v2",
    "eleven_turbo_v2_5",
    "eleven_flash_v2_5",
}
# eleven_v4_turbo က Burmese (my) ထောက်ပံ့တယ် (84 ဘာသာစကား) — မူရင်း model
MAX_ELEVEN_TEXT_LEN = 5000

MAX_TEXT_LEN = 5000
RATE_RE = re.compile(r"^[+-]?\d{1,3}%$")
MAX_AUDIO_B64_LEN = 20_000_000


class TTSRequest(BaseModel):
    text: str
    voice: str = "my-MM-ThihaNeural"
    rate: str = "+0%"

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("text ဗလာဖြစ်နေပါတယ်")
        if len(v) > MAX_TEXT_LEN:
            raise ValueError(f"စာအရှည် {MAX_TEXT_LEN} လုံးထက် မပိုရပါ")
        return v

    @field_validator("voice")
    @classmethod
    def voice_known(cls, v: str) -> str:
        v = (v or "").strip()
        if v not in VOICES:
            raise ValueError("voice က my-MM-ThihaNeural (သို့) my-MM-NilarNeural ပဲ ဖြစ်ရမယ်")
        return VOICES[v]

    @field_validator("rate")
    @classmethod
    def rate_ok(cls, v: str) -> str:
        v = (v or "+0%").strip()
        if not RATE_RE.match(v):
            raise ValueError("rate က +0% ပုံစံပဲ ဖြစ်ရမယ် (ဥပမာ +10%, -10%)")
        num = int(v[:-1])
        if num < -50 or num > 100:
            raise ValueError("rate က -50% ကနေ +100% အတွင်းပဲ ဖြစ်ရမယ်")
        sign = "+" if num >= 0 else ""
        return f"{sign}{num}%"


class GeminiTestRequest(BaseModel):
    key: str
    model: str = "gemini-3.8-flash"

    @field_validator("key")
    @classmethod
    def key_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Gemini API Key ဗလာဖြစ်နေပါတယ်")
        return v

    @field_validator("model")
    @classmethod
    def model_known(cls, v: str) -> str:
        v = (v or "").strip()
        if v not in GEMINI_MODELS:
            raise ValueError("model မမှန်ပါ")
        return v


class GeminiSrtRequest(BaseModel):
    key: str
    model: str = "gemini-3.8-flash"
    audio_base64: str
    language: str = "myanmar"
    narration_style: str = "story"
    chunk_start_seconds: float = 0.0
    story_context: str = ""

    @field_validator("key")
    @classmethod
    def key_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Gemini API Key ဗလာဖြစ်နေပါတယ်")
        return v

    @field_validator("model")
    @classmethod
    def model_known(cls, v: str) -> str:
        v = (v or "").strip()
        if v not in GEMINI_MODELS:
            raise ValueError("model မမှန်ပါ")
        return v

    @field_validator("audio_base64")
    @classmethod
    def audio_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("audio ဗလာဖြစ်နေပါတယ်")
        if len(v) > MAX_AUDIO_B64_LEN:
            raise ValueError("audio အပိုင်း ကြီးလွန်းပါတယ် — Video အတိုနဲ့ ပြန်စမ်းပါ")
        return v


class ElevenTtsRequest(BaseModel):
    key: str
    voice_id: str
    model: str = "eleven_v4_turbo"
    text: str
    stability: float = 0.5
    similarity_boost: float = 0.75

    @field_validator("key")
    @classmethod
    def key_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("ElevenLabs API Key ဗလာဖြစ်နေပါတယ်")
        return v

    @field_validator("voice_id")
    @classmethod
    def voice_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Voice ရွေးပါ")
        return v

    @field_validator("model")
    @classmethod
    def model_known(cls, v: str) -> str:
        v = (v or "").strip()
        if v not in ELEVEN_MODELS:
            raise ValueError("model မမှန်ပါ")
        return v

    @field_validator("text")
    @classmethod
    def text_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("text ဗလာဖြစ်နေပါတယ်")
        if len(v) > MAX_ELEVEN_TEXT_LEN:
            raise ValueError(f"စာအရှည် {MAX_ELEVEN_TEXT_LEN} လုံးထက် မပိုရပါ — အပိုင်းခွဲပြီး ထုတ်ပါ")
        return v

    @field_validator("stability", "similarity_boost")
    @classmethod
    def range_0_1(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class ElevenVoicesRequest(BaseModel):
    key: str

    @field_validator("key")
    @classmethod
    def key_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("ElevenLabs API Key ဗလာဖြစ်နေပါတယ်")
        return v


async def make_mp3(text: str, voice: str, rate: str) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(tmp.name)
        return tmp.name
    except Exception:
        try:
            os.remove(tmp.name)
        except OSError:
            pass
        raise


def gemini_text_from_response(data: dict) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""


async def call_gemini(key: str, model: str, contents: list, timeout: float = 120.0):
    """Server ဘက်ကနေ Google Gemini ကို ခေါ်တယ် (Browser CORS မခံရဘူး)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json={"contents": contents})
    return resp.status_code, resp.json() if resp.content else {}


@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!doctype html><html lang="my"><head><meta charset="utf-8">
<title>NPZ Edge TTS + Gemini Proxy Server</title></head><body style="font-family:sans-serif;max-width:640px;margin:40px auto;padding:0 16px">
<h1>NPZ Edge TTS + Gemini + ElevenLabs Proxy Server ✅</h1>
<p>Thiha / Nilar အသံကို MP3 ထုတ်ပေးတယ် + Gemini SRT ကို Server ဘက်ကနေ ခေါ်ပေးတယ် + ElevenLabs အသံကို Server ဘက်ကနေ ခေါ်ပေးတယ်။</p>
<p>TTS စမ်းဖို့: <a href="/tts?text=%E1%80%99%E1%80%84%E1%80%BA%E1%80%82%E1%80%9C%E1%80%AC%E1%80%95%E1%80%AB&voice=my-MM-NilarNeural">/tts?text=မင်္ဂလာပါ&voice=my-MM-NilarNeural</a></p>
<p>App ထဲမှာ ဒီ Server ရဲ့ URL ကို ထည့်ရမယ် — ဥပမာ https://xxx.up.railway.app</p>
</body></html>"""


@app.get("/health")
async def health():
    return {"ok": True, "voices": list(VOICES.keys())[:2], "gemini": True, "elevenlabs": True}


@app.post("/tts")
async def tts_post(req: TTSRequest):
    try:
        mp3_path = await make_mp3(req.text, req.voice, req.rate)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Edge TTS မရပါ: {e}")
    return FileResponse(mp3_path, media_type="audio/mpeg", filename="npz-tts.mp3")


@app.get("/tts")
async def tts_get(text: str = "", voice: str = "my-MM-ThihaNeural", rate: str = "+0%"):
    try:
        req = TTSRequest(text=text, voice=voice, rate=rate)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        mp3_path = await make_mp3(req.text, req.voice, req.rate)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Edge TTS မရပါ: {e}")
    return FileResponse(mp3_path, media_type="audio/mpeg", filename="npz-tts.mp3")


@app.post("/gemini-test")
async def gemini_test(req: GeminiTestRequest):
    contents = [{"parts": [{"text": "မင်္ဂလာပါ လို့ မြန်မာလို ပြန်ဖြေပါ။"}]}]
    try:
        status, data = await call_gemini(req.key, req.model, contents, timeout=30.0)
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "Gemini timeout"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"Gemini ခေါ်မရပါ: {e}"})
    if status != 200:
        err = ""
        try:
            err = data.get("error", {}).get("message", "")
        except AttributeError:
            err = ""
        return JSONResponse(status_code=status, content={"ok": False, "status": status, "error": err})
    return {"ok": True, "status": 200, "text": gemini_text_from_response(data)}


@app.post("/gemini-srt")
async def gemini_srt(req: GeminiSrtRequest):
    start = max(0.0, float(req.chunk_start_seconds or 0.0))
    lang_text = "မြန်မာ" if req.language in ("myanmar", "my", "မြန်မာ") else req.language
    style_text = req.narration_style or "story"
    story_ctx = (req.story_context or "").strip()
    story_part = (
        f"Story so far (earlier parts of this same video — use it to keep character names, "
        f"places and the plot consistent across cues; do NOT repeat it verbatim, just keep "
        f"the narration continuous with it): {story_ctx} "
        if story_ctx
        else ""
    )
    prompt = (
        "You are a movie-recap narrator, NOT a transcriber. Listen to the audio in this clip "
        "and return ONLY a valid SRT subtitle file containing timed RECAP NARRATION. "
        "Do NOT transcribe, quote, copy or translate word-for-word what the characters say. "
        "Instead, understand what is HAPPENING in each timed part and write third-person "
        "storytelling narration that summarizes the scene and the action — what the characters "
        "do, where they are, and what happens next — like the narration of a movie-recap video. "
        f"Language: {lang_text} — write every narration line ONLY in {lang_text}, whatever "
        "language is spoken in the audio; never output text in the audio's original language "
        "and never mix languages. "
        f"Narration style: {style_text}. "
        + story_part
        + f"The clip starts at {start:.1f} seconds in the original video, so SRT timestamps must start from there. "
        "Each cue: number, HH:MM:SS,mmm --> HH:MM:SS,mmm, then ONE short narration sentence (1-2 lines max). "
        "Cues must never overlap: each cue ends before the next one starts. "
        "Do not add any explanation, markdown, or extra text — output SRT only."
    )
    contents = [
        {
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "audio/wav", "data": req.audio_base64}},
            ]
        }
    ]
    try:
        status, data = await call_gemini(req.key, req.model, contents, timeout=120.0)
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "Gemini timeout (120s)"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"Gemini ခေါ်မရပါ: {e}"})
    if status != 200:
        err = ""
        try:
            err = data.get("error", {}).get("message", "")
        except AttributeError:
            err = ""
        return JSONResponse(status_code=status, content={"ok": False, "status": status, "error": err})
    raw = gemini_text_from_response(data)
    # Gemini က ```srt ... ``` နဲ့ ပြန်ပေးတတ်လို့ အဲဒါကို ခွာတယ်
    srt = raw.strip()
    if srt.startswith("```"):
        srt = re.sub(r"^```[a-zA-Z]*\n?", "", srt)
        srt = re.sub(r"\n?```\s*$", "", srt).strip()
    return {"ok": True, "status": 200, "srt": srt, "raw_text": raw}


def eleven_error_text(status: int, data) -> str:
    try:
        detail = data.get("detail", {})
        if isinstance(detail, dict):
            return detail.get("message", "") or str(detail)
        return str(detail)
    except AttributeError:
        return ""


@app.post("/eleven-voices")
async def eleven_voices(req: ElevenVoicesRequest):
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": req.key},
            )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "ElevenLabs timeout"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"ElevenLabs ခေါ်မရပါ: {e}"})
    if resp.status_code != 200:
        try:
            data = resp.json()
        except Exception:
            data = {}
        return JSONResponse(
            status_code=resp.status_code,
            content={"ok": False, "status": resp.status_code, "error": eleven_error_text(resp.status_code, data)},
        )
    data = resp.json()
    voices = [
        {
            "voice_id": v.get("voice_id", ""),
            "name": v.get("name", ""),
            "labels": v.get("labels", {}) or {},
            "category": v.get("category", ""),
        }
        for v in data.get("voices", [])
        if v.get("voice_id")
    ]
    return {"ok": True, "status": 200, "voices": voices}


@app.post("/eleven-tts")
async def eleven_tts(req: ElevenTtsRequest):
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{req.voice_id}"
        "?output_format=mp3_44100_128"
    )
    body = {
        "text": req.text,
        "model_id": req.model,
        "voice_settings": {
            "stability": req.stability,
            "similarity_boost": req.similarity_boost,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={"xi-api-key": req.key, "Content-Type": "application/json"},
            )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "ElevenLabs timeout (120s)"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"ElevenLabs ခေါ်မရပါ: {e}"})
    if resp.status_code != 200:
        try:
            data = resp.json()
        except Exception:
            data = {}
        return JSONResponse(
            status_code=resp.status_code,
            content={"ok": False, "status": resp.status_code, "error": eleven_error_text(resp.status_code, data)},
        )
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.write(resp.content)
    tmp.close()
    return FileResponse(tmp.name, media_type="audio/mpeg", filename="npz-elevenlabs.mp3")


# ---------------------------------------------------------------------------
# Video Search — Bilibili / Rednote (NPZ Studio Video Search အတွက်)
# App က POST JSON (Content-Type: text/plain လည်း ရ) နဲ့ ခေါ်တယ်။
# Bilibili: public API — login/cookie မလို (guest လမ်း)။
# Rednote (Xiaohongshu): public API မရှိ — best-effort သာ, မရရင်
# {ok: false, error} ပြန်ပြီး App က မူရင်း site ဖွင့်ဖို့ ခလုတ်ပြတယ်။
# ---------------------------------------------------------------------------

BILI_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}
REDNOTE_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.xiaohongshu.com/",
    "Origin": "https://www.xiaohongshu.com",
}


def _clean_bili_title(t: str) -> str:
    t = re.sub(r"<[^>]+>", "", t or "")
    return (
        t.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .strip()
    )


def _bili_duration_sec(s) -> int:
    if isinstance(s, (int, float)):
        return int(s)
    parts = str(s or "0").split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    total = 0
    for n in nums:
        total = total * 60 + n
    return total


class BilibiliSearchRequest(BaseModel):
    q: str = ""
    query: str = ""
    keyword: str = ""
    text: str = ""
    page: int = 1


class BilibiliPlayurlRequest(BaseModel):
    bvid: str = ""
    id: str = ""
    bv: str = ""
    cid: int = 0
    guest: bool = True


class RednoteSearchRequest(BaseModel):
    q: str = ""
    query: str = ""
    keyword: str = ""
    text: str = ""
    page: int = 1


class RednoteResolveRequest(BaseModel):
    url: str = ""
    link: str = ""
    shareUrl: str = ""


@app.post("/bilibili-search")
async def bilibili_search(req: BilibiliSearchRequest):
    q = (req.q or req.query or req.keyword or req.text or "").strip()
    if not q:
        return JSONResponse(status_code=422, content={"ok": False, "error": "ရှာမယ့် စာသား ထည့်ပါ"})
    page = max(1, int(req.page or 1))
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=BILI_UA) as client:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/search/type",
                params={"keyword": q, "search_type": "video", "page": page},
            )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "Bilibili timeout"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"Bilibili ခေါ်မရပါ: {e}"})
    if resp.status_code != 200:
        return JSONResponse(status_code=resp.status_code, content={"ok": False, "status": resp.status_code, "error": "Bilibili search မရပါ"})
    try:
        data = resp.json()
    except Exception:
        return JSONResponse(status_code=502, content={"ok": False, "error": "Bilibili ပြန်ပေးတာ ဖတ်မရပါ"})
    if data.get("code") != 0:
        return JSONResponse(status_code=502, content={"ok": False, "error": data.get("message", "Bilibili search မရပါ")})
    items = (data.get("data") or {}).get("result") or []
    results = []
    for v in items:
        if not isinstance(v, dict):
            continue
        bvid = v.get("bvid", "")
        if not bvid:
            continue
        pic = v.get("pic", "") or ""
        if pic.startswith("//"):
            pic = "https:" + pic
        dur = v.get("duration", "") or ""
        results.append(
            {
                "bvid": bvid,
                "title": _clean_bili_title(v.get("title", "")),
                "author": v.get("author", "") or "",
                "duration": dur,
                "duration_sec": _bili_duration_sec(dur),
                "pic": pic,
                "cover": pic,
                "thumbnail": pic,
                "play": v.get("play", 0) or 0,
                "danmaku": v.get("danmaku", 0) or 0,
                "url": f"https://www.bilibili.com/video/{bvid}",
            }
        )
    return {"ok": True, "results": results, "videos": results, "items": results, "page": page}


@app.post("/bilibili-playurl")
async def bilibili_playurl(req: BilibiliPlayurlRequest):
    bvid = (req.bvid or req.id or req.bv or "").strip()
    if not bvid:
        return JSONResponse(status_code=422, content={"ok": False, "error": "bvid ဗလာဖြစ်နေပါတယ်"})
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=BILI_UA) as client:
            # 1) cid ယူမယ် (view API — login မလို)
            view = await client.get(
                "https://api.bilibili.com/x/web-interface/view", params={"bvid": bvid}
            )
            cid = int(req.cid or 0)
            if view.status_code == 200:
                try:
                    pages = (view.json().get("data") or {}).get("pages") or []
                    if pages and not cid:
                        cid = int(pages[0].get("cid") or 0)
                except Exception:
                    pass
            if not cid:
                return JSONResponse(
                    status_code=502,
                    content={"ok": False, "error": "ဒီ video ရဲ့ cid မရပါ — down လို့မရနိုင်ပါ"},
                )
            # 2) guest playurl — qn 64 (720p) → 32 → 16, ရတာယူမယ်
            for qn in (64, 32, 16):
                play = await client.get(
                    "https://api.bilibili.com/x/player/playurl",
                    params={"bvid": bvid, "cid": cid, "qn": qn, "fnval": 0},
                )
                if play.status_code != 200:
                    continue
                try:
                    pdata = play.json().get("data") or {}
                except Exception:
                    continue
                durl = pdata.get("durl") or []
                if durl and durl[0].get("url"):
                    url = durl[0]["url"]
                    if url.startswith("http://"):
                        url = "https://" + url[len("http://"):]
                    return {
                        "ok": True,
                        "url": url,
                        "video_url": url,
                        "download_url": url,
                        "bvid": bvid,
                        "cid": cid,
                        "quality": {64: "720p", 32: "480p", 16: "360p"}.get(qn, ""),
                        "size": durl[0].get("size", 0),
                    }
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "Bilibili timeout"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"Bilibili ခေါ်မရပါ: {e}"})
    return JSONResponse(
        status_code=502,
        content={"ok": False, "error": "ဒီ video ကို guest လမ်းနဲ့ down လို့မရပါ (login/VIP/region လိုနိုင်တယ်) — Bilibili မှာ ဖွင့်ကြည့်ပါ"},
    )


@app.post("/rednote-search")
async def rednote_search(req: RednoteSearchRequest):
    q = (req.q or req.query or req.keyword or req.text or "").strip()
    if not q:
        return JSONResponse(status_code=422, content={"ok": False, "error": "ရှာမယ့် စာသား ထည့်ပါ"})
    # Xiaohongshu public API မရှိ — edith search ကို best-effort စမ်းမယ်
    # (x-s signature မပါရင် 99% ကျရှုံးတယ်; ကျရှုံးရင် App က site ဖွင့်ဖို့ ခလုတ်ပြတယ်)
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=REDNOTE_UA) as client:
            resp = await client.post(
                "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes",
                json={"keyword": q, "page": max(1, int(req.page or 1)), "page_size": 20, "sort": "general", "note_type": 0},
            )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "Rednote timeout"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"Rednote ခေါ်မရပါ: {e}"})
    try:
        data = resp.json()
    except Exception:
        data = {}
    if resp.status_code != 200 or data.get("code") != 0:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": "Rednote search မရပါ (Rednote က API ဖွင့်မပေးဘူး) — Rednote App/Web မှာ ရှာပြီး link ကို Downloader မှာ paste လုပ်ပါ"},
        )
    notes = []
    for item in (data.get("data") or {}).get("items") or []:
        note = (item or {}).get("note_card") or {}
        nid = note.get("note_id", "")
        if not nid:
            continue
        cover = ""
        if isinstance(note.get("cover"), dict):
            info_list = (note.get("cover") or {}).get("info_list") or []
            if info_list:
                cover = info_list[0].get("url", "") or ""
        user = note.get("user") or {}
        notes.append(
            {
                "note_id": nid,
                "title": note.get("display_title", "") or "",
                "author": user.get("nickname", "") if isinstance(user, dict) else "",
                "cover": cover,
                "thumbnail": cover,
                "url": f"https://www.xiaohongshu.com/explore/{nid}",
            }
        )
    return {"ok": True, "results": notes, "notes": notes, "items": notes, "page": max(1, int(req.page or 1))}


@app.post("/rednote-resolve")
async def rednote_resolve(req: RednoteResolveRequest):
    url = (req.url or req.link or req.shareUrl or "").strip()
    if not url:
        return JSONResponse(status_code=422, content={"ok": False, "error": "Rednote link ထည့်ပါ"})
    if not url.startswith("http"):
        url = "https://" + url
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=REDNOTE_UA, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "Rednote timeout"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"Rednote ခေါ်မရပါ: {e}"})
    if resp.status_code != 200:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": "Rednote စာမျက်နှာ ဖွင့်မရပါ (Rednote က block လုပ်နေနိုင်တယ်) — Rednote App မှာ down လုပ်ပြီး တင်ပါ"},
        )
    html = resp.text or ""
    video_url = ""
    title = ""
    cover = ""
    note_id = ""
    m = re.search(r"/explore/([0-9a-f]{24})", str(resp.url))
    if m:
        note_id = m.group(1)
    # og meta ကနေ အရင်ယူမယ်
    og_video = re.search(r'<meta[^>]+property=["\']og:video(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']', html)
    if not og_video:
        og_video = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video(?::secure_url)?["\']', html)
    if og_video:
        video_url = og_video.group(1).replace("&amp;", "&")
    og_title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']*)["\']', html)
    if not og_title:
        og_title = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:title["\']', html)
    if og_title:
        title = og_title.group(1)
    og_image = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
    if not og_image:
        og_image = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html)
    if og_image:
        cover = og_image.group(1).replace("&amp;", "&")
    # og:video မပါရင် __INITIAL_STATE__ ထဲက masterUrl ကို ရှာမယ်
    if not video_url:
        for mu in re.findall(r'"masterUrl"\s*:\s*"([^"]+)"', html):
            mu = mu.replace("\\/", "/").replace("\\u0026", "&")
            if mu.startswith("http"):
                video_url = mu
                break
    if not video_url:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": "ဒီ link က video URL ဖြေမရပါ (Rednote က block လုပ်နေတာ (သို့) ဒီ note မှာ video မပါတာ ဖြစ်နိုင်တယ်) — Rednote App မှာ down လုပ်ပြီး တင်ပါ"},
        )
    return {
        "ok": True,
        "url": video_url,
        "video_url": video_url,
        "download_url": video_url,
        "title": title,
        "cover": cover,
        "note_id": note_id,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
