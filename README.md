<div align="center">

# ⚡ TELRO

**دستیار همه‌کاره‌ی تلگرام | The all-in-one Telegram assistant**

دانلود از ۲۰+ پلتفرم · موزیک · هوش مصنوعی · تصویرساز · پنل مدیریت

`Python 3.11+` · `aiogram 3` · `yt-dlp` · `SQLite (WAL)` · `Docker`

</div>

---

## ✨ چه کاری انجام می‌دهد؟

| قابلیت | توضیح |
| --- | --- |
| 📥 **دانلود از هر لینک** | یوتیوب، اینستاگرام، تیک‌تاک، توییتر/X، ردیف، ساندکلود، فیسبوک، ویمیو، پینترست، لینکدین، توییچ، اسپاتیفای، تلگرام و لینک مستقیم فایل |
| 🎚 **انتخاب کیفیت** | 144p تا 4K (هر کیفیتی که منبع داشته باشد)، MP3 با بیتریت دلخواه، یا فایل اصلی بدون تغییر |
| 📚 **پلی‌لیست** | دانلود همه‌ی آیتم‌ها یا فقط اولین ویدیو، با گزارش پیشرفت و امکان لغو |
| 🎵 **جست‌وجوی موزیک** | اسم آهنگ یا خواننده را بفرست؛ ۵ نتیجه‌ی برتر، پیش‌نمایش، و تبدیل به MP3 |
| 🤖 **چت هوش مصنوعی** | پاسخ استریمی (تایپ زنده)، حافظه‌ی گفتگو برای هر کاربر، ارسال عکس با قابلیت تحلیل تصویر، و ویس با تبدیل به متن |
| 🎨 **تصویرساز** | تولید تصویر از پرامپت (فارسی یا انگلیسی) با نسبت‌های 1:1، 16:9، 9:16 و 4:5 |
| ⚡ **کش هوشمند** | فایلی که یک بار دانلود شده، برای کاربر دیگر در چند ثانیه ارسال می‌شود |
| 💎 **سهمیه و اشتراک** | سهمیه‌ی روزانه‌ی رایگان، اشتراک ویژه، سیستم دعوت با پاداش خودکار |
| 🔐 **Force-join** | عضویت اجباری در کانال‌ها با پشتیبانی از یوزرنیم، آیدی و لینک دعوت |
| 🛡 **پنل مدیریت** | آمار زنده، پیام همگانی با پیش‌نمایش، مدیریت کاربران (بن/اشتراک)، حالت تعمیر، پاک‌سازی کش |
| 🌐 **دو زبانه** | فارسی (پیش‌فرض) و انگلیسی، با چیدمان کامل RTL و تغییر زبان در هر لحظه |
| 🚀 **سرعت** | دانلود موازی، ۸ فرگمنت همزمان، صف هوشمند، کش، و ارسال در حین دانلود |

## 🚀 راه‌اندازی سریع

### ۱) پیش‌نیازها

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y python3.12 python3.12-venv ffmpeg curl
```

> `ffmpeg` برای تبدیل MP3، ادغام ویدیو/صدا و فشرده‌سازی لازم است. بدون آن، دانلود ویدیوی ترکیبی و MP3 کار نمی‌کند.

### ۲) نصب

```bash
git clone https://github.com/RwinFu/TELRO-BOT.git
cd TELRO-BOT

python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt

cp .env.example .env
nano .env      # BOT_TOKEN را بگذار
```

توکن را از [@BotFather](https://t.me/BotFather) بگیرید. برای پیدا کردن آیدی عددی خودتان، بعد از بالا آمدن ربات `/id` بفرستید و آن را در `OWNER_IDS` قرار دهید.

### ۳) اجرا

```bash
.venv/bin/python -m bot
```

یا با Make:

```bash
make install      # ساخت .venv + نصب وابستگی‌ها
make run          # اجرای ربات
make test         # اجرای تست‌ها
make lint         # بررسی کد
```

### ۴) با Docker (پیشنهادی برای سرور)

```bash
cp .env.example .env && nano .env
docker compose up -d --build
docker compose logs -f bot
```

سلامتی سرویس روی `http://SERVER:8080/health` در دسترس است (برای UptimeRobot و مانیتورینگ).

## ⌨️ دستورها

| دستور | کار |
| --- | --- |
| `/start` | منوی اصلی و لینک دعوت |
| `/menu` | منوی اصلی |
| `/dl <لینک>` | دانلود از لینک (بدون دستور هم کار می‌کند) |
| `/music <نام>` | جست‌وجوی موزیک |
| `/ai <سؤال>` | شروع چت با هوش مصنوعی (`/exit` برای خروج) |
| `/img <پرامپت>` | ساخت تصویر |
| `/settings` | زبان، کیفیت پیش‌فرض، فرمت صدا، کپشن |
| `/account` | حساب من: سهمیه، اشتراک، آمار |
| `/invite` | لینک دعوت و پیشرفت جایزه |
| `/premium` | معرفی اشتراک ویژه |
| `/help` | راهنما |
| `/id` | نمایش آیدی عددی شما |
| `/admin` | پنل مدیریت (فقط مدیران) |

## ⚙️ تنظیمات مهم

همه‌ی مقادیر از `.env` خوانده می‌شوند. فهرست کامل در [`.env.example`](.env.example) آمده است؛ مهم‌ترین‌ها:

| کلید | پیش‌فرض | توضیح |
| --- | --- | --- |
| `BOT_TOKEN` | — | توکن ربات (الزامی) |
| `BOT_USERNAME` | `Rwinro_bot` | برای ساخت لینک دعوت |
| `OWNER_IDS` / `ADMIN_IDS` | خالی | آیدی‌های عددی مدیران، با کاما جدا شوند |
| `MAX_UPLOAD_MB` | `0` | `0` = خودکار (۵۰ مگ با API ابری، ۲ گیگ با API محلی) |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | تعداد دانلود همزمان (روی سرور قوی‌تر بالا ببرید) |
| `YTDLP_FRAGMENTS` | `8` | تعداد اتصال موازی برای هر دانلود |
| `FREE_DOWNLOADS_PER_DAY` | `25` | سهمیه‌ی روزانه‌ی کاربر عادی |
| `FREE_AI_PER_DAY` | `60` | سهمیه‌ی پیام AI روزانه |
| `AI_BASE_URL` / `AI_MODEL` | Pollinations / `openai` | هر سرویس سازگار با OpenAI (OpenAI، OpenRouter، Groq، Ollama…) |
| `IMAGE_PROVIDER` | `pollinations` | `pollinations` (رایگان) یا `openai` |
| `FORCE_JOIN_CHANNELS` | خالی | `@channel`، `-1001234567890` یا لینک دعوت، با کاما جدا شوند |
| `SUPPORT_USERNAME` | خالی | یوزرنیم پشتیبانی برای دکمه‌ی تماس |
| `ENABLE_GROUPS` | `false` | اجازه‌ی استفاده در گروه‌ها |
| `TELEGRAM_API_SERVER` | خالی | آدرس Bot API محلی برای آپلود تا ۲ گیگ |

> **نکته‌ی امنیتی:** فایل `.env` را هرگز commit نکنید (در `.gitignore` هست). در صورت لو رفتن توکن، از BotFather آن را `/revoke` کنید.

## 🏎 چرا سریع‌تر است؟

- **همه‌چیز async است** — هیچ عملیات شبکه‌ای یا دیسکی بلاک‌کننده در مسیر هندلرها نیست.
- **دانلود موازی** — هر ویدیو با ۸ فرگمنت همزمان دانلود می‌شود (`YTDLP_FRAGMENTS`)، و چند دانلود هم به‌صورت موازی اجرا می‌شوند.
- **کش فایل** — با `file_id` تلگرام؛ دانلود تکراری صفر ثانیه.
- **پاسخ استریمی AI** — متن هم‌زمان با تولید مدل نمایش داده می‌شود و هر ۱٫۲ ثانیه ادیت می‌شود (بدون فلود).
- **صف منصفانه** — هر کاربر قفل اختصاصی و کل سیستم سقف همزمانی دارد تا یک نفر سرور را اشغال نکند.
- **بدون دانلود اضافی** — لینک مستقیم با یک HEAD request بررسی می‌شود، نه با yt-dlp.
- **پیش‌نمایش سریع** — کارت اطلاعات ویدیو قبل از انتخاب کیفیت، با متادیتای استخراج‌شده در حافظه.

## 🧱 ساختار پروژه

```text
bot/
├── config.py            # تنظیمات (pydantic-settings + .env)
├── i18n.py              # موتور ترجمه، fa/en
├── locales/             # فایل‌های ترجمه (~۲۶۰ کلید)
├── db/repository.py     # لایه‌ی SQLite: کاربر، سهمیه، کش، آمار، حافظه AI
├── keyboards/           # تمام کیبوردهای اینلاین
├── middlewares/         # کاربر، throttle، force-join، محافظ مدیر
├── handlers/            # start, download, music, ai, image, settings, admin, groups
├── services/
│   ├── downloader/      # inspector, engine (yt-dlp), direct, manager, sender
│   └── ai/              # client (SSE/JSON), prompts, images
├── utils/               # متن، URL، فرمت اعداد، تلگرام
├── web/health.py        # /health برای مانیتورینگ
└── main.py              # bootstrap، دیسپچر، خطاها، خاموشی تمیز
tests/                   # ۸۴ تست واحد (pytest)
docs/                    # راهنمای استقرار و معماری
```

## 🐳 استقرار حرفه‌ای

راهنمای کامل: [`docs/deploy.md`](docs/deploy.md) — شامل systemd، Docker، Nginx، بکاپ، آپدیت بدون قطعی و **Bot API محلی برای آپلود ۲ گیگابایتی**.

معماری و تصمیم‌های فنی: [`docs/architecture.md`](docs/architecture.md).

## 🧪 توسعه

```bash
make dev        # نصب وابستگی‌های توسعه
make test       # pytest
make lint       # ruff
make format     # فرمت خودکار
```

CI روی هر push اجرا می‌شود (`.github/workflows/ci.yml`): lint + تست روی Python 3.11 و 3.12.

## ❓ سؤالات پرتکرار

<details>
<summary><b>دانلود از اینستاگرام کار نمی‌کند / خطای login می‌دهد</b></summary>

اینستاگرام برای محتوای عمومی معمولاً بدون کوکی کار می‌کند، اما برای استوری و پیج‌های خصوصی به کوکی نیاز است. فایل `cookies.txt` را در ریشه‌ی پروژه بگذارید و `COOKIES_FILE=cookies.txt` را تنظیم کنید.
</details>

<details>
<summary><b>فایل بزرگ‌تر از ۵۰ مگ آپلود نمی‌شود</b></summary>

این محدودیت خود تلگرام با API ابری است. برای رفع آن، Bot API محلی را بالا بیاورید — راهنما در [`docs/deploy.md`](docs/deploy.md#-آپلود-۲-گیگابایتی-bot-api-محلی).
</details>

<details>
<summary><b>AI جواب نمی‌دهد</b></summary>

سرویس پیش‌فرض Pollinations رایگان است و گاهی شلوغ می‌شود. یک ارائه‌دهنده‌ی سازگار با OpenAI (OpenAI، OpenRouter، Groq، Ollama) را در `.env` تنظیم کنید تا پایداری کامل داشته باشید.
</details>

<details>
<summary><b>چطور ادمین شوم؟</b></summary>

`/id` را به ربات بفرستید، عدد را در `OWNER_IDS` بگذارید و ربات را ری‌استارت کنید. سپس `/admin`.
</details>

## 📄 مجوز

MIT — استفاده، تغییر و انتشار آزاد است. ساخته‌شده برای [@Rwinro_bot](https://t.me/Rwinro_bot).

---

<div dir="ltr" align="left">

## English

**TELRO** is a production-ready all-in-one Telegram bot: a **multi-platform downloader** (YouTube, Instagram, TikTok, X, Reddit, SoundCloud, Spotify search, direct links…) with **quality/MP3 selection**, **playlist support**, a **streaming AI assistant** with per-user memory, **image generation**, quotas & referrals, **force-join**, a full **admin panel**, and a **Persian-first / English** UI.

**Why it's fast:** fully async aiogram 3, 8 parallel yt-dlp fragments, per-user job locks + a global concurrency queue, Telegram `file_id` caching, streaming AI responses, and a HEAD-first fast path for direct links.

### Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # set BOT_TOKEN (and OWNER_IDS after /id)
.venv/bin/python -m bot
```

Docker: `docker compose up -d --build` → health check at `:8080/health`.

See [`docs/deploy.md`](docs/deploy.md) for systemd, local Bot API (2 GB uploads), backups and zero-downtime updates; [`docs/architecture.md`](docs/architecture.md) for the design.

### Tests

```bash
pip install -r requirements-dev.txt
pytest -q          # 84 tests
ruff check bot tests
```

MIT licensed.

</div>
