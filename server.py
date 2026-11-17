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
  POST /assembly-test  -> JSON {key} -> {ok} (AssemblyAI Key စမ်းမယ်)
  POST /assembly-start -> JSON {key, audio_base64, source_language, target_languages}
                       -> {ok, transcript_id} (audio တင် + transcribe + translate တောင်းမယ်)
  POST /assembly-status -> JSON {key, transcript_id, target_language}
                       -> {ok, transcript_status, myanmar_text, cues: [{start, end, text}]}
                       (ပြီးရင် မြန်မာ ဘာသာပြန် + အချိန်ပါတဲ့ စာကြောင်းတွေ ပြန်ပေးတယ်)
  GET  /messenger-webhook -> Meta webhook verification (hub.mode / hub.verify_token / hub.challenge)
  POST /messenger-webhook -> Facebook Page ကို လာတဲ့ စာတွေ လက်ခံ + keyword နဲ့ auto-reply ပြန်ပို့တယ်
                       (FB_PAGE_ACCESS_TOKEN / FB_VERIFY_TOKEN / FB_PAGE_ID / FB_APP_SECRET ကို
                       Railway Variables ထဲမှာပဲ ထည့်ရမယ် — code / GitHub ထဲ မထည့်ရ)

အသံများ:
  my-MM-ThihaNeural (အမျိုးသား) / my-MM-NilarNeural (အမျိုးသမီး)
TTS အတွက် Key မလိုပါ — edge-tts က Microsoft Edge TTS ကို တိုက်ရိုက်သုံးပါတယ်။
Gemini အတွက် NPZ ရဲ့ကိုယ်ပိုင် API Key ကို App ထဲကနေ တစ်ခါသုံးအဖြစ် ပို့ရမယ် —
Server က Key ကို ဘယ်နေရာမှ မသိမ်းဘူး, Google ကို ခေါ်ပြီးတာနဲ့ မေ့လိုက်တယ်။
ElevenLabs အတွက်လည်း အတူတူပဲ — NPZ ရဲ့ကိုယ်ပိုင် ElevenLabs API Key ကို
App ထဲကနေ တစ်ခါသုံးအဖြစ် ပို့ရမယ်, Server က Key ကို ဘယ်နေရာမှ မသိမ်းဘူး။
ElevenLabs v4 model က Burmese (my) ထောက်ပံ့တယ် — အသံကောင်းမကောင်း စမ်းကြည့်ရမယ်။
Free tier: တစ်လ 10,000 characters (~10 မိနစ်), commercial use မရ။
AssemblyAI အတွက်လည်း အတူတူပဲ — NPZ ရဲ့ကိုယ်ပိုင် AssemblyAI API Key ကို
App / စာမျက်နှာကနေ တစ်ခါသုံးအဖြစ် ပို့ရမယ်, Server က Key ကို ဘယ်နေရာမှ မသိမ်းဘူး။
AssemblyAI: Universal-2 transcription $0.15 / audio နာရီ + Translation $0.06 / audio နာရီ;
အကောင့်အသစ် $50 free credits (ကတ်မလို)။ မြန်မာ (my) ကို translation target အဖြစ်
ထောက်ပံ့လား — စာမျက်နှာမှာ အတည်မပြုနိုင်သေးဘူး; /assembly-status က
translation_ok နဲ့ ပြန်ပြောတယ်။

Run (local):
  pip install -r requirements.txt
  uvicorn server:app --host 0.0.0.0 --port 8000
"""
import base64
import hashlib
import hmac
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import edge_tts
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
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
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro-preview",
    "gemini-3.7-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
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


FOOTBALL_LEAGUES = {"eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "uefa.champions"}
NEWS_UA = {"User-Agent": "Mozilla/5.0 (compatible; NPZNewsRecap/1.0)"}


class NewsFetchRequest(BaseModel):
    url: str
    limit: int = 20

    @field_validator("url")
    @classmethod
    def url_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL က http(s):// နဲ့ စရမယ်")
        return v

    @field_validator("limit")
    @classmethod
    def limit_ok(cls, v: int) -> int:
        return max(1, min(50, int(v or 20)))


class FootballRequest(BaseModel):
    league: str = "eng.1"
    date: str = ""

    @field_validator("league")
    @classmethod
    def league_known(cls, v: str) -> str:
        v = (v or "").strip()
        if v not in FOOTBALL_LEAGUES:
            raise ValueError("လိဂ် မမှန်ပါ")
        return v

    @field_validator("date")
    @classmethod
    def date_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not re.fullmatch(r"\d{8}", v):
            raise ValueError("date က YYYYMMDD ပုံစံ ဖြစ်ရမယ်")
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
<p>Facebook Messenger webhook: <code>https://xxx.up.railway.app/messenger-webhook</code> (FB_PAGE_ACCESS_TOKEN / FB_VERIFY_TOKEN ကို Railway Variables ထဲမှာ ထည့်ရမယ်)</p>
<hr>
<h2>🎙️ AssemblyAI စမ်းမည် — တရုတ် အသံ → မြန်မာ ဘာသာပြန်</h2>
<p>AssemblyAI API Key ကို အောက်မှာ ထည့်ပါ — Key ကို ဘယ်နေရာမှ မသိမ်းဘူး (ဒီ စာမျက်နှာမှာပဲ သုံးတယ်)။ Audio ဖိုင် (mp3/wav) ရွေးပြီး <b>▶ Translate စမ်းမည်</b> နှိပ်ပါ — Server က AssemblyAI ကို တင် + စာသားထုတ် + မြန်မာလို ပြန်ပေးပြီး အခြေအနေ ပြပေးမယ်။ မြန်မာ (my) ပြန်မလာရင် AssemblyAI က my ကို မထောက်ပံ့တာပါ။</p>
<p>Key: <input id="aKey" type="password" placeholder="AssemblyAI API Key" style="width:320px"> <button onclick="aTest()">Key စမ်းမည်</button> <span id="aTestOut"></span></p>
<p>အသံ ဖိုင်: <input id="aFile" type="file" accept="audio/*,video/*"></p>
<p>အသံ ဘာသာ: <select id="aLang"><option value="zh">တရုတ် (zh)</option><option value="en">အင်္ဂလိပ် (en)</option><option value="auto">Auto</option></select>
<button onclick="aStart()">▶ Translate စမ်းမည်</button></p>
<pre id="aOut" style="white-space:pre-wrap;background:#111;color:#eee;padding:12px;border-radius:8px">...</pre>
<script>
let aTimer=null;
async function aPost(path,body){
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'text/plain'},body:JSON.stringify(body)});
  return r.json();
}
async function aTest(){
  const k=document.getElementById('aKey').value.trim();
  document.getElementById('aTestOut').textContent='စစ်နေတယ်…';
  try{const d=await aPost('/assembly-test',{key:k});document.getElementById('aTestOut').textContent=d.ok?'✅ Key ရတယ်':'❌ '+(d.error||d.status);}catch(e){document.getElementById('aTestOut').textContent='❌ '+e;}
}
async function aStart(){
  const k=document.getElementById('aKey').value.trim();
  const f=document.getElementById('aFile').files[0];
  const out=document.getElementById('aOut');
  if(!k){out.textContent='Key ထည့်ပါ';return;}
  if(!f){out.textContent='အသံ ဖိုင် ရွေးပါ';return;}
  out.textContent='Audio တင်နေတယ်…';
  const b64=await new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result.split(',')[1]);r.onerror=rej;r.readAsDataURL(f);});
  let d;
  try{d=await aPost('/assembly-start',{key:k,audio_base64:b64,source_language:document.getElementById('aLang').value,target_languages:['my']});}catch(e){out.textContent='❌ '+e;return;}
  if(!d.ok){out.textContent='❌ '+(d.error||d.status);return;}
  const id=d.transcript_id;
  out.textContent='⏳ Transcribe + Translate လုပ်နေတယ်… (id: '+id+')';
  if(aTimer)clearInterval(aTimer);
  aTimer=setInterval(async()=>{
    let s;
    try{s=await aPost('/assembly-status',{key:k,transcript_id:id,target_language:'my'});}catch(e){out.textContent='❌ '+e;clearInterval(aTimer);return;}
    if(!s.ok){out.textContent='❌ '+(s.error||s.status);clearInterval(aTimer);return;}
    if(s.transcript_status!=='completed'){out.textContent='⏳ '+s.transcript_status+'…';return;}
    clearInterval(aTimer);
    let t='✅ ပြီးပြီ!\n\n';
    t+='— မြန်မာ စာသား အပြည့် —\n'+(s.myanmar_text||'(မြန်မာ ပြန်မလာပါ)')+'\n\n';
    if(s.warning)t+='⚠️ '+s.warning+'\n\n';
    t+='— စာကြောင်း အလိုက် (အချိန် + မြန်မာ) —\n';
    (s.cues||[]).forEach((c,i)=>{t+=(i+1)+'. ['+c.start+'s - '+c.end+'s] '+c.text+'\n';});
    if(!(s.cues||[]).length)t+='(cue မရှိပါ — မြန်မာ ပြန်မလာတာ ဖြစ်နိုင်တယ်)\n';
    t+='\n— မူရင်း စာသား —\n'+(s.text||'');
    out.textContent=t;
  },3000);
}
</script>
</body></html>"""


@app.get("/health")
async def health():
    return {"ok": True, "voices": list(VOICES.keys())[:2], "gemini": True, "elevenlabs": True, "assemblyai": True, "messenger": True, "news": True, "football": True}


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


# ---------------------------------------------------------------------------
# AssemblyAI — Transcribe + Translate (တရုတ် အသံ → မြန်မာ ဘာသာပြန် စမ်းဖို့)
# API key ကို App / client က တစ်ခါသုံးအဖြစ် ပို့ရမယ် — Server က Key ကို
# ဘယ်နေရာမှ မသိမ်းဘူး (Gemini / ElevenLabs နဲ့ အတူတူပဲ)။
# Universal-2 (99 ဘာသာ — တရုတ် + မြန်မာ ပါ): $0.15 / audio နာရီ
# Translation add-on: $0.06 / audio နာရီ — 86 ဘာသာသို့ ပြန်ပေးတယ်။
# မြန်မာ (my) ကို translation target အဖြစ် ထောက်ပံ့လား — AssemblyAI စာမျက်နှာမှာ
# အတည်မပြုနိုင်သေးဘူး; /assembly-status က translation_ok နဲ့ ပြန်ပြောတယ်။
# Translation က စာသား အပြည့်ပဲ ပြန်ပေးတာ — အချိန်ပါတဲ့ SRT တိုက်ရိုက်မရဘူး;
# speaker labels + match_original_utterance နဲ့ utterance တစ်ပိုင်းချင်းစီကို
# မြန်မာလို ပြန်ပေးတယ်, utterance တွေမှာ start/end (ms) ပါလို့ အဲဒါကနေ SRT cue လုပ်လို့ရတယ်။
# ---------------------------------------------------------------------------

ASSEMBLY_BASE = "https://api.assemblyai.com/v2"
ASSEMBLY_MODEL = "universal-2"


class AssemblyKeyRequest(BaseModel):
    key: str

    @field_validator("key")
    @classmethod
    def key_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("AssemblyAI API Key ဗလာဖြစ်နေပါတယ်")
        return v


class AssemblyStartRequest(BaseModel):
    key: str
    audio_base64: str
    source_language: str = "zh"
    target_languages: list = ["my"]

    @field_validator("key")
    @classmethod
    def key_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("AssemblyAI API Key ဗလာဖြစ်နေပါတယ်")
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

    @field_validator("source_language")
    @classmethod
    def lang_ok(cls, v: str) -> str:
        v = (v or "zh").strip().lower()
        return v or "zh"

    @field_validator("target_languages")
    @classmethod
    def targets_ok(cls, v) -> list:
        if isinstance(v, str):
            v = [v]
        langs = []
        for t in v or ["my"]:
            t = str(t or "").strip().lower()
            if t and t not in langs:
                langs.append(t)
        return langs[:3] or ["my"]


class AssemblyStatusRequest(BaseModel):
    key: str
    transcript_id: str
    target_language: str = "my"

    @field_validator("key")
    @classmethod
    def key_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("AssemblyAI API Key ဗလာဖြစ်နေပါတယ်")
        return v

    @field_validator("transcript_id")
    @classmethod
    def tid_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("transcript_id ဗလာဖြစ်နေပါတယ်")
        return v

    @field_validator("target_language")
    @classmethod
    def target_ok(cls, v: str) -> str:
        v = (v or "my").strip().lower()
        return v or "my"


def assembly_error_text(status: int, data) -> str:
    try:
        err = data.get("error", "")
        if isinstance(err, dict):
            return err.get("message", "") or str(err)
        return str(err or "")
    except AttributeError:
        return ""


def shape_assembly_result(data: dict, target: str = "my") -> dict:
    """AssemblyAI completed transcript ကို App သုံးလို့လွယ်တဲ့ ပုံစံ ပြောင်းတယ်.
    utterance တစ်ပိုင်းချင်းစီ = SRT cue တစ်ကြောင်း (start/end စက္ကန့် + မြန်မာစာသား)."""
    translated = data.get("translated_texts") or {}
    if not isinstance(translated, dict):
        translated = {}
    my_text = translated.get(target, "") or ""
    cues = []
    utterances = []
    for u in data.get("utterances") or []:
        if not isinstance(u, dict):
            continue
        start = (u.get("start") or 0) / 1000.0
        end = (u.get("end") or 0) / 1000.0
        ut = u.get("translated_texts") or {}
        if not isinstance(ut, dict):
            ut = {}
        ut_my = ut.get(target, "") or ""
        utterances.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "speaker": u.get("speaker"),
                "text": u.get("text", "") or "",
                "translated": ut_my,
            }
        )
        if ut_my:
            cues.append({"start": round(start, 3), "end": round(end, 3), "text": ut_my})
    words = []
    for w in data.get("words") or []:
        if not isinstance(w, dict):
            continue
        words.append(
            {
                "text": w.get("text", "") or "",
                "start": round((w.get("start") or 0) / 1000.0, 3),
                "end": round((w.get("end") or 0) / 1000.0, 3),
                "speaker": w.get("speaker"),
            }
        )
    return {
        "text": data.get("text", "") or "",
        "language_code": data.get("language_code", "") or "",
        "myanmar_text": my_text,
        "translation_ok": bool(my_text),
        "translated_texts": translated,
        "utterances": utterances,
        "cues": cues,
        "words": words,
    }


@app.post("/assembly-test")
async def assembly_test(req: AssemblyKeyRequest):
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{ASSEMBLY_BASE}/transcript",
                params={"limit": 1},
                headers={"Authorization": req.key},
            )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "AssemblyAI timeout"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"AssemblyAI ခေါ်မရပါ: {e}"})
    if resp.status_code != 200:
        try:
            data = resp.json()
        except Exception:
            data = {}
        return JSONResponse(
            status_code=resp.status_code,
            content={"ok": False, "status": resp.status_code, "error": assembly_error_text(resp.status_code, data) or "AssemblyAI Key မမှန်ပါ"},
        )
    return {"ok": True, "status": 200}


@app.post("/assembly-start")
async def assembly_start(req: AssemblyStartRequest):
    try:
        audio_bytes = base64.b64decode(req.audio_base64, validate=False)
    except Exception:
        return JSONResponse(status_code=422, content={"ok": False, "error": "audio base64 မမှန်ပါ"})
    if not audio_bytes:
        return JSONResponse(status_code=422, content={"ok": False, "error": "audio ဗလာဖြစ်နေပါတယ်"})
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # 1) audio တင်မယ်
            up = await client.post(
                f"{ASSEMBLY_BASE}/upload",
                content=audio_bytes,
                headers={"Authorization": req.key, "Content-Type": "application/octet-stream"},
            )
            if up.status_code != 200:
                try:
                    data = up.json()
                except Exception:
                    data = {}
                return JSONResponse(
                    status_code=up.status_code,
                    content={"ok": False, "status": up.status_code, "error": assembly_error_text(up.status_code, data) or "AssemblyAI upload မရပါ"},
                )
            upload_url = (up.json() or {}).get("upload_url", "")
            if not upload_url:
                return JSONResponse(status_code=502, content={"ok": False, "error": "AssemblyAI upload_url မရပါ"})
            # 2) transcript + translation တောင်းမယ်
            body = {
                "audio_url": upload_url,
                "speech_model": ASSEMBLY_MODEL,
                "speaker_labels": True,
                "speech_understanding": {
                    "request": {
                        "translation": {
                            "target_languages": req.target_languages,
                            "match_original_utterance": True,
                            "formal": False,
                        }
                    }
                },
            }
            if (req.source_language or "zh").lower() == "auto":
                body["language_detection"] = True
            else:
                body["language_code"] = req.source_language
            tr = await client.post(
                f"{ASSEMBLY_BASE}/transcript",
                json=body,
                headers={"Authorization": req.key, "Content-Type": "application/json"},
            )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "AssemblyAI timeout (120s)"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"AssemblyAI ခေါ်မရပါ: {e}"})
    if tr.status_code != 200:
        try:
            data = tr.json()
        except Exception:
            data = {}
        return JSONResponse(
            status_code=tr.status_code,
            content={"ok": False, "status": tr.status_code, "error": assembly_error_text(tr.status_code, data) or "AssemblyAI transcript တောင်းမရပါ"},
        )
    tr_data = tr.json() or {}
    tid = tr_data.get("id", "")
    if not tid:
        return JSONResponse(status_code=502, content={"ok": False, "error": "AssemblyAI transcript_id မရပါ"})
    return {"ok": True, "status": 200, "transcript_id": tid, "transcript_status": tr_data.get("status", "")}


@app.post("/assembly-status")
async def assembly_status(req: AssemblyStatusRequest):
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{ASSEMBLY_BASE}/transcript/{req.transcript_id}",
                headers={"Authorization": req.key},
            )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "AssemblyAI timeout"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"AssemblyAI ခေါ်မရပါ: {e}"})
    if resp.status_code != 200:
        try:
            data = resp.json()
        except Exception:
            data = {}
        return JSONResponse(
            status_code=resp.status_code,
            content={"ok": False, "status": resp.status_code, "error": assembly_error_text(resp.status_code, data) or "AssemblyAI status ဖတ်မရပါ"},
        )
    data = resp.json()
    st = (data.get("status") or "").lower()
    if st == "error":
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": data.get("error", "") or "AssemblyAI transcription error"})
    if st != "completed":
        return {"ok": True, "status": 200, "transcript_status": st}
    shaped = shape_assembly_result(data, target=req.target_language)
    out = {"ok": True, "status": 200, "transcript_status": "completed", **shaped}
    if not shaped["translation_ok"]:
        out["warning"] = "မြန်မာ (my) ဘာသာပြန် ပြန်မလာပါ — AssemblyAI က my ကို translation target အဖြစ် မထောက်ပံ့တာ ဖြစ်နိုင်တယ်"
    return out


# ---------------------------------------------------------------------------
# Facebook Messenger Auto-Reply (ifonemaster Page အတွက်)
# Meta (Facebook) က Page ကို လာတဲ့ စာတွေကို ဒီ Server ကို webhook နဲ့ ပို့တယ်;
# Server က keyword ကြည့်ပြီး အဖြေ အလိုလို ပြန်ပို့တယ် (Send API)။
#
# လိုတာ (Railway Variables ထဲမှာပဲ ထည့်ရမယ် — code / GitHub / chat ထဲ လုံးဝ မထည့်ရ):
#   FB_PAGE_ACCESS_TOKEN — Page ရဲ့ access token (Meta App Dashboard ကနေ ယူရမယ်)
#   FB_VERIFY_TOKEN      — ကိုယ်တိုင် သတ်မှတ်တဲ့ စကားဝှက် (Meta Dashboard မှာ ရိုက်တဲ့ စာနဲ့ တူရမယ်)
#   FB_PAGE_ID           — (optional) Page ID သိရင် ထည့်; မထည့်ရင် /me/messages လမ်းနဲ့ ပို့တယ်
#   FB_APP_SECRET        — (optional) App Secret ထည့်ထားရင် webhook signature ကို စစ်တယ်
#
# Graph API v26.0 (current, 2026-07-29) သုံးတယ် — v21.0 က 2027-01-21 မှာ ပိတ်မယ်။
# Send API: POST https://graph.facebook.com/v26.0/{PAGE_ID}/messages
#   (သို့) /me/messages — {recipient: {id}, message: {text}, messaging_type: "RESPONSE"}
# Webhook verify: GET ?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
#   — token တူရင် challenge ကို အတိုင်း ပြန်ပေးတယ်။
# Webhook POST: X-Hub-Signature-256 (HMAC-SHA256, App Secret) — secret ရှိမှ စစ်တယ်။
# Meta က 200 OK ကို 5 စက္ကန့်အတွင်း မျှော်တယ် — ဒါကြောင့် အမြဲ 200 ပြန်တယ်,
# ပို့မရရင်တောင် log ပဲ ရေးပြီး 200 ပြန်တယ် (မပြန်ရင် Meta က webhook ကို ပိတ်နိုင်တယ်)။
#
# ကန့်သတ်ချက် (အမှန်):
# - RESPONSE အဖြေက user နောက်ဆုံး စာပို့ပြီး 24 နာရီအတွင်းပဲ ရတယ်။
# - App က Development mode မှာ ရှိတုန်း admin/tester တွေရဲ့ စာပဲ ရတယ်;
#   လူတိုင်းကို auto-reply ပြန်ချင်ရင် App ကို Live လုပ်ပြီး pages_messaging အတွက်
#   App Review အောင်ရမယ် (Meta စစ်တာ ရက်ပိုင်းကြာနိုင်တယ်)။
# - ဒါက keyword အဖြေပဲ — AI စကားပြော မဟုတ်ဘူး။ စာသားတွေ အောက်မှာ ပြင်လို့ရတယ်။
# ---------------------------------------------------------------------------

FB_GRAPH_VERSION = "v26.0"
FB_GRAPH_BASE = f"https://graph.facebook.com/{FB_GRAPH_VERSION}"

# --- ဒီနေရာမှာ ပြန်မယ့် စာသားတွေ ပြင်လို့ရတယ် ---
# keyword တွေ ပါရင် အဲဒီ အဖြေကို ပြန်တယ် (အပေါ်က အတန်းက အရင် စစ်တယ်);
# ဘာမှ မတိုက်ရင် MESSENGER_FALLBACK ကို ပြန်တယ်။
MESSENGER_REPLIES = [
    (
        ["apple id", "apple"],
        "🍎 Apple ID အကောင့် — 15,000 ကျပ် / 100 ဘတ် ပါ။\n"
        "ဝယ်ယူရန်: နာမည်နဲ့ ဖုန်းနံပါတ် ပို့ပေးပါ။ အကောင့် ရပြီးမှ ငွေချေရပါတယ်။\n"
        "📞 0952980185",
    ),
    (
        ["gemini"],
        "✨ Google Gemini 1 Year — 500 ဘတ် ပါ။\n"
        "ဝယ်ယူရန် နာမည်နဲ့ ဖုန်းနံပါတ် ပို့ပေးပါ။\n"
        "📞 0952980185",
    ),
    (
        ["icloud", "unlock"],
        "🔓 iCloud Unlock Service ရှိပါတယ်။\n"
        "ဖုန်း model နဲ့ အခြေအနေ ပြောပေးပါ — လူကိုယ်တိုင် ပြန်ဖြေပေးပါမယ်။\n"
        "📞 0952980185",
    ),
    (
        ["ဈေး", "စျေး", "price", "ဘယ်လောက်"],
        "🛍️ ifonemaster စျေးနှုန်း —\n"
        "🍎 Apple ID: 15,000 ကျပ် / 100 ဘတ်\n"
        "✨ Google Gemini 1 Year: 500 ဘတ်\n"
        "🔓 iCloud Unlock Service: စုံစမ်းရန်\n"
        "ဝယ်ယူရန် နာမည်နဲ့ ဖုန်းနံပါတ် ပို့ပေးပါ။",
    ),
    (
        ["pay", "ငွေ", "binance", "truemoney", "true money", "kpay", "bank", "လွဲ"],
        "💳 ငွေချေလို့ရတဲ့ နည်းတွေ — Binance, TrueMoney, Bank Transfer, KPay ပါ။\n"
        "Apple ID ကတော့ အကောင့် ရပြီးမှ ငွေချေရပါတယ်။",
    ),
    (
        ["ဝယ်", "buy", "လိုချင်"],
        "ဝယ်ယူရန် နာမည်နဲ့ ဖုန်းနံပါတ် ပို့ပေးပါ။\n"
        "🍎 Apple ID: 15,000 ကျပ် / 100 ဘတ်\n"
        "✨ Google Gemini 1 Year: 500 ဘတ်\n"
        "🔓 iCloud Unlock Service: စုံစမ်းရန်",
    ),
    (
        ["မင်္ဂလာပါ", "hello", "hey", "hi"],
        "မင်္ဂလာပါ 🙏 ifonemaster ပါ။\n"
        "🍎 Apple ID: 15,000 ကျပ် / 100 ဘတ်\n"
        "✨ Gemini 1 Year: 500 ဘတ်\n"
        "🔓 iCloud Unlock Service\n"
        "ဘာလိုချင်လဲ ပြောပေးပါ — ဥပမာ 'Apple ID' လို့ ရိုက်ပါ။",
    ),
]

MESSENGER_FALLBACK = (
    "မင်္ဂလာပါ 🙏 ifonemaster ပါ။ မေးချင်တာ နားမလည်လို့ —\n"
    "🍎 Apple ID: 15,000 ကျပ် / 100 ဘတ်\n"
    "✨ Gemini 1 Year: 500 ဘတ်\n"
    "🔓 iCloud Unlock Service\n"
    "'Apple ID' / 'Gemini' / 'ဈေး' လို့ ရိုက်ပြီး မေးလို့ရပါတယ်။ "
    "လူကိုယ်တိုင် မကြာခင် ပြန်ဖြေပေးပါမယ်။\n"
    "📞 0952980185"
)


def _kw_hit(text: str, kw: str) -> bool:
    """keyword ပါမပါ စစ်တယ် — စကားလုံး အစမှာ ပါရင် ရတယ်
    ('this' ထဲက 'hi' လို အလယ်မှာ ပါတာ မယူဘူး; 'ဈေးနှုန်း' ထဲက 'ဈေး' လို
    အစမှာ ပါတာတော့ ယူတယ် — မြန်မာစာက စကားလုံးတွဲ ဖြစ်တတ်လို့)."""
    kw = (kw or "").lower()
    if not kw:
        return False
    return re.search(r"(?<!\w)" + re.escape(kw), text) is not None


def match_messenger_reply(text: str) -> str:
    t = (text or "").lower()
    for keywords, reply in MESSENGER_REPLIES:
        if any(_kw_hit(t, k) for k in keywords):
            return reply
    return MESSENGER_FALLBACK


def fb_verify_signature(raw: bytes, signature: str) -> bool:
    secret = os.environ.get("FB_APP_SECRET", "").strip()
    if not secret:
        return True  # App Secret မထည့်ထားရင် မစစ်ပါ (စမ်းသပ်နေတုန်း)
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + expected, signature)


async def fb_send_message(sender_id: str, text: str) -> bool:
    token = os.environ.get("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not token:
        print("[messenger] FB_PAGE_ACCESS_TOKEN မရှိပါ — စာပြန်မပို့ပါ (Railway Variables ထဲ ထည့်ပါ)")
        return False
    page_id = os.environ.get("FB_PAGE_ID", "").strip()
    node = page_id if page_id else "me"
    url = f"{FB_GRAPH_BASE}/{node}/messages"
    body = {
        "recipient": {"id": sender_id},
        "message": {"text": text},
        "messaging_type": "RESPONSE",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, params={"access_token": token}, json=body)
    except Exception as e:
        print(f"[messenger] send error: {e}")
        return False
    if resp.status_code != 200:
        print(f"[messenger] send failed {resp.status_code}: {resp.text[:300]}")
        return False
    return True


@app.get("/messenger-webhook")
async def messenger_verify(request: Request):
    params = request.query_params
    mode = params.get("hub.mode", "")
    token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")
    verify_token = os.environ.get("FB_VERIFY_TOKEN", "").strip()
    if mode == "subscribe" and verify_token and token == verify_token:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="verify token မမှန်ပါ")


@app.post("/messenger-webhook")
async def messenger_webhook(request: Request):
    raw = await request.body()
    if not fb_verify_signature(raw, request.headers.get("x-hub-signature-256", "")):
        raise HTTPException(status_code=403, detail="signature မမှန်ပါ")
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return {"ok": True}
    if not isinstance(data, dict) or data.get("object") != "page":
        return {"ok": True}
    for entry in data.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for ev in entry.get("messaging") or []:
            if not isinstance(ev, dict):
                continue
            msg = ev.get("message") or {}
            if not isinstance(msg, dict) or msg.get("is_echo"):
                continue
            text = (msg.get("text") or "").strip()
            sender = (ev.get("sender") or {}).get("id", "")
            if not text or not sender:
                continue
            reply = match_messenger_reply(text)
            await fb_send_message(sender, reply)
    return {"ok": True}


def _parse_news_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _strip_html(text: str) -> str:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


@app.post("/news-fetch")
async def news_fetch(req: NewsFetchRequest):
    url = req.url
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=NEWS_UA, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "သတင်းဆိုက် timeout"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"သတင်းဆိုက် ခေါ်မရပါ: {e}"})
    if resp.status_code != 200:
        return JSONResponse(status_code=resp.status_code, content={"ok": False, "status": resp.status_code, "error": "သတင်းဆိုက် မရပါ"})
    body = resp.text or ""
    head = body[:2000]
    if "<rss" in head or "<feed" in head or body.lstrip().startswith("<?xml"):
        try:
            root = ET.fromstring(body)
        except Exception:
            return JSONResponse(status_code=502, content={"ok": False, "error": "RSS ဖတ်မရပါ"})
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)
        items = []
        dated = False
        for el in root.iter():
            if _local(el.tag) not in ("item", "entry"):
                continue
            fields = {}
            for child in el:
                name = _local(child.tag)
                if name == "link":
                    fields.setdefault("link", (child.get("href") or "") or (child.text or "").strip())
                elif name in ("title", "pubDate", "published", "updated", "description", "summary"):
                    fields[name] = (child.text or "").strip()
            title = fields.get("title", "")
            if not title:
                continue
            pub = fields.get("pubDate") or fields.get("published") or fields.get("updated") or ""
            dt = _parse_news_date(pub)
            if dt is not None:
                dated = True
                if dt < cutoff:
                    continue
            desc = _strip_html(fields.get("description") or fields.get("summary") or "")[:500]
            items.append({"title": title, "link": fields.get("link", ""), "published": pub, "published_ts": dt.timestamp() if dt else None, "description": desc})
            if len(items) >= req.limit:
                break
        return {"ok": True, "kind": "feed", "items": items, "count": len(items), "only_24h": dated, "source": url}
    m = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.S | re.I)
    title = _strip_html(m.group(1)) if m else ""
    return {"ok": True, "kind": "article", "title": title, "text": _strip_html(body)[:8000], "source": url}


@app.post("/football")
async def football(req: FootballRequest):
    params = {}
    if req.date.strip():
        params["dates"] = req.date.strip()
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=NEWS_UA) as client:
            resp = await client.get(
                f"https://site.api.espn.com/apis/site/v2/sports/soccer/{req.league}/scoreboard",
                params=params,
            )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"ok": False, "status": 504, "error": "ESPN timeout"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "status": 502, "error": f"ESPN ခေါ်မရပါ: {e}"})
    if resp.status_code != 200:
        return JSONResponse(status_code=resp.status_code, content={"ok": False, "status": resp.status_code, "error": "ESPN မရပါ"})
    try:
        data = resp.json()
    except Exception:
        return JSONResponse(status_code=502, content={"ok": False, "error": "ESPN ပြန်ပေးတာ ဖတ်မရပါ"})
    matches = []
    for ev in data.get("events") or []:
        if not isinstance(ev, dict):
            continue
        comps = ev.get("competitions") or []
        comp = comps[0] if comps else {}
        home = away = None
        for c in comp.get("competitors") or []:
            if not isinstance(c, dict):
                continue
            team = c.get("team") or {}
            side = {"name": team.get("displayName", ""), "short": team.get("shortDisplayName", ""), "score": c.get("score", ""), "winner": bool(c.get("winner"))}
            if c.get("homeAway") == "home":
                home = side
            else:
                away = side
        scorers = []
        for d in comp.get("details") or []:
            if not isinstance(d, dict):
                continue
            athletes = d.get("athletes") or []
            names = ", ".join(a.get("displayName", "") for a in athletes if isinstance(a, dict) and a.get("displayName"))
            scorers.append({
                "minute": (d.get("clock") or {}).get("displayValue", ""),
                "team": (d.get("team") or {}).get("shortDisplayName", ""),
                "type": (d.get("type") or {}).get("text", ""),
                "players": names,
            })
        matches.append({
            "id": ev.get("id", ""),
            "date": ev.get("date", ""),
            "name": ev.get("name", ""),
            "status": (ev.get("status") or {}).get("type", {}).get("detail", ""),
            "home": home,
            "away": away,
            "scorers": scorers,
            "venue": (comp.get("venue") or {}).get("fullName", ""),
        })
    return {"ok": True, "league": req.league, "matches": matches, "count": len(matches)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
