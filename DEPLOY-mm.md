# 🔊 Edge TTS + Gemini Proxy Server ကို တင်နည်း (NPZ Movie Recap Studio အတွက်)

ဒီ Server က App ထဲကနေ ဖုန်း Chrome မှာပါ **Thiha / Nilar အသံအစစ် (MP3)**
ရအောင် လုပ်ပေးတာပါ။ Server မတင်ရသေးရင် App က ဖုန်း built-in အသံပဲ ကျမယ်။

**အသစ်ထည့်ထားတာ — Gemini Proxy:** Browser ကနေ Google Gemini ကို
တိုက်ရိုက်ခေါ်လို့ မရလို့ (Failed to fetch) Gemini SRT ကိုလည်း ဒီ Server
တစ်ခု တည်းကပဲ ခေါ်ပေးတယ် — `POST /gemini-test` (Key စမ်းဖို့) နဲ့
`POST /gemini-srt` (အသံကို SRT ပြောင်းဖို့)။ Server ထပ်တင်စရာ မလိုဘူး —
ဒီ Server တစ်ခုတည်း Deploy လုပ်ရင် အသံ + SRT နှစ်ခုလုံး ရမယ်။
App ထဲမှာ **Edge Server URL** အပြင် **Gemini Server URL** အကွက်ပါ ပါတယ် —
နှစ်ခုလုံးမှာ ဒီ Server ရဲ့ URL အတူတူ ထည့်လို့ရတယ်။

**ဒီ Server မှာ Key / Token ဘာမှ မလိုဘူး။** BotFather token လည်း မလိုဘူး။
GitHub မှာ token ထည့်စရာ မရှိဘူး — ဘာမှ မတင်မိအောင် သတိထားပါ။

---

## အဆင့် ၁ — GitHub ပေါ် ကုဒ်တင်ပါ

1. https://github.com မှာ အကောင့်ဖွင့် (အခမဲ့)
2. **New repository** နှိပ် → နာမည်ပေး (ဥပမာ `npz-edge-tts-server`) → **Create**
3. ဒီ folder (`edge-tts-server`) ထဲက ဖိုင်အားလုံး —
   `server.py`, `requirements.txt`, `Procfile`, `Dockerfile`, `render.yaml` —
   ကို repo ထဲ တင်ပါ (GitHub ဝဘ်ဆိုက်က **uploading an existing file** ကနေ ဆွဲချတင်လို့ရတယ်)

## အဆင့် ၂ — Hosting ရွေးပါ (တစ်ခုပဲ လိုတယ်)

### နည်းလမ်း A: Railway (အလွယ်ဆုံး)

1. https://railway.app မှာ GitHub အကောင့်နဲ့ ဝင်ပါ
2. **New Project** → **Deploy from GitHub repo** → ကိုယ့် repo ရွေးပါ
3. Deploy ပြီးရင် **Settings → Networking → Generate Domain** နှိပ်ပါ
4. ရလာတဲ့ URL ကို ကူးထားပါ — ဥပမာ `https://npz-edge-tts-server.up.railway.app`
5. Browser မှာ အဲဒီ URL ဖွင့်ကြည့်ပါ — **“NPZ Edge TTS Server ✅”** ပေါ်ရင် ရပြီ
6. `/health` ပါ ထပ်ဖွင့်ကြည့်ပါ — `{"ok": true}` ပေါ်ရင် အဆင်ပြေပြီ

### နည်းလမ်း B: Render

1. https://render.com မှာ GitHub အကောင့်နဲ့ ဝင်ပါ
2. **New** → **Web Service** → ကိုယ့် repo ရွေးပါ
3. Build Command: `pip install -r requirements.txt`
   Start Command: `uvicorn server:app --host 0.0.0.0 --port $PORT`
4. **Create Web Service** နှိပ်ပါ — Deploy ပြီးရင် URL ရမယ်
   (ဥပမာ `https://npz-edge-tts-server.onrender.com`)
5. အခမဲ့ plan မှာ ပထမဆုံး ခေါ်ရင် ၃၀-၆၀ စက္ကန့်လောက် စောင့်ရတတ်တယ်
   (server အိပ်နေလို့ — ခေါ်ပြီးရင် နိုးလာမယ်)

## အဆင့် ၃ — App ထဲမှာ Server URL ထည့်ပါ

1. **NPZ Movie Recap Studio** App ကို ဖွင့်ပါ
2. အသံ အပိုင်းမှာ **“Edge Server URL”** ဆိုတဲ့ အကွက်ကို ရှာပါ
3. အဆင့် ၂ က ရတဲ့ URL ကို အဲဒီမှာ ကူးထည့်ပါ
   (နောက်ဆုံး `/` မပါအောင် ထည့်ပါ — ဥပမာ `https://xxx.up.railway.app`)
4. **“Server စမ်းမည်”** ခလုတ်နှိပ်ပြီး စမ်းပါ — Thiha/Nilar အသံ ကျလာရင် ရပြီ ✅
5. အဲဒီနောက်ပိုင်း **“Edge အသံနဲ့ ဖတ်မည်”** နှိပ်တိုင်း Server ကနေ MP3 ရပြီး
   **MP3 Download** ခလုတ်လည်း ပွင့်မယ်

## အဆင့် ၄ — Local ကွန်ပျူတာမှာ စမ်းချင်ရင် (မလိုလည်း ရတယ်)

```
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
```

Browser မှာ http://localhost:8000 ဖွင့်ကြည့်ပါ။

---

## ⚠️ သတိပြုရန်

- Server URL ကို **Chat မှာ မပို့ပါနဲ့** — App ထဲက အကွက်မှာပဲ ထည့်ပါ
  (URL ကိုယ်တိုင်က လျှို့ဝှက်ချက် မဟုတ်ပေမဲ့ App ထဲမှာ ထည့်တာက အမှန်ဆုံးပါ)
- စာအရှည် **၅၀၀၀ လုံး** ထက် မပိုရပါ — ရှည်ရင် အပိုင်းခွဲပြီး ခေါ်ပါ
- Rate က **-50% ကနေ +100%** အတွင်းပဲ ရပါတယ်
- အခမဲ့ Hosting မှာ လစဉ် နာရီ/ဒေတာ အကန့်အသတ်ရှိတယ် —
  Recap တစ်ပိုင်းစာ အသံထုတ်ဖို့တော့ လုံလောက်ပါတယ်
- Server အိပ်နေရင် (Render အခမဲ့) ပထမအခေါက် ခေါ်တာ ကြာတတ်တယ် —
  ထပ်ခေါ်ကြည့်ပါ
