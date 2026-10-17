# 🧠 معماری TELRO

این سند تصمیم‌های فنی، مسیر درخواست‌ها و نقاطی که روی سرعت و پایداری اثر دارند را توضیح می‌دهد.

---

## نمای کلی

```text
Telegram
   │  long polling (aiogram 3)
   ▼
Dispatcher
   ├── outer middlewares: UserMiddleware → Throttling → ForceJoin → AdminGuard
   ├── routers: start → download → music → ai → image → settings → admin → groups → fallback
   │
   ├── DownloadManager ── inspector (yt-dlp, metadata only)
   │                       ├── DownloadsEngine (yt-dlp, fragments=8)
   │                       ├── DirectDownloader (HEAD/GET + SSRF guard)
   │                       ├── MediaSender (upload, split, compress)
   │                       └── cache (Telegram file_id)
   ├── AIClient ── SSE streaming → live-edited message
   ├── ImageService ── pollinations / OpenAI images
   ├── Repository (aiosqlite, WAL) → data/telro.db
   └── HealthServer (aiohttp, :8080/health) + cleanup loop
```

---

## ۱) چرا این معماری سریع است؟

### الف) Async سرتاسری

هر I/O (شبکه، دیسک، دیتابیس) غیرمسدودکننده است. `aiosqlite` در یک thread جدا اجرا می‌شود، `aiohttp` برای دانلود مستقیم و AI، و yt-dlp با `asyncio.to_thread` فقط در بخش‌های CPU-bound و همگام خودش. نتیجه: ربات در حین دانلود یک فایل ۵۰۰ مگابایتی، به بقیه کاربران هم فوری جواب می‌دهد.

### ب) موازی‌سازی دانلود

- `YTDLP_FRAGMENTS=8` → هر ویدیو با ۸ اتصال همزمان (HLS/DASH) دانلود می‌شود.
- `MAX_CONCURRENT_DOWNLOADS=2` → چند کار همزمان، اما با سقف برای جلوگیری از اشباع CPU/دیسک.
- لینک مستقیم اصلاً از yt-dlp رد نمی‌شود: یک `HEAD` سریع + دانلود chunked با `aiohttp`. برای فایل‌های CDN این چند ثانیه صرفه‌جویی می‌کند.
- کارت اطلاعات (metadata) فقط یک استخراج سبک است؛ دانلود واقعی تا انتخاب کاربر شروع نمی‌شود.

### ج) صف و قفل منصفانه

```text
job → per-user asyncio.Lock   (جلوگیری از دو دانلود همزمان یک کاربر)
    → global asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    → progress callback هر ۱ ثانیه (throttle شده)
```

اگر کاربر دیگری در حال دانلود باشد، وضعیت روی «در صف…» می‌ماند و به‌محض آزاد شدن ظرفیت، بدون دخالت کاربر شروع می‌شود.

### د) کش `file_id`

کلید کش از پلتفرم + شناسه‌ی محتوا + کیفیت ساخته می‌شود. بعد از آپلود موفق، `file_id` در جدول `file_cache` ذخیره می‌شود. درخواست بعدی (حتی از کاربر دیگر) با `send_video(file_id=…)` در **کمتر از یک ثانیه** ارسال می‌شود. اگر `file_id` منقضی یا نامعتبر باشد، به‌صورت خودکار پاک و دانلود تازه انجام می‌شود.

### ه) ادیت هوشمند پیام

پیشرفت دانلود و پاسخ استریمی AI با throttle ادیت می‌شوند (۱ ثانیه برای دانلود، ~۱٫۲ ثانیه برای AI) تا هم تجربه‌ی زنده داشته باشیم و هم به محدودیت Flood تلگرام نخوریم.

---

## ۲) جریان دانلود

```text
پیام حاوی لینک
   ↓ detect_platform / extract_urls
   ↓ quota check
   ↓ (direct?) HEAD → کارت فایل
   ↓ inspector.inspect → MediaInfo (عنوان، مدت، کیفیت‌ها، پلی‌لیست؟)
   ↓ کارت کیفیت (یا دانلود خودکار اگر کاربر «بهترین کیفیت» را پیش‌فرض کرده باشد)
   ↓ consume_download (ثبت سهمیه)
   ↓ DownloadManager.create_job + start
       ↓ lock کاربر + semaphore
       ↓ engine.download → فایل روی دیسک
       ↓ sender: حجم مجاز؟ → compress با ffmpeg (در صورت نیاز) → upload
       ↓ cache_put(file_id)
       ↓ پاک‌سازی پوشه‌ی موقت
```

اگر ارسال شکست بخورد، `refund_download` سهمیه را برمی‌گرداند. اگر کاربر Cancel بزند، job با یک رویداد `asyncio` متوقف و فایل‌ها پاک می‌شوند؛ تلاش دوباره با دکمه‌ی «🔁» همان کارت انجام می‌شود.

### خطاها

`services/downloader/errors.py` متن خطای خام yt-dlp را به کلید ترجمه تبدیل می‌کند: `private`, `age`, `geo`, `unsupported`, `unavailable`, `network`, `forbidden`, `rate_limit`, `format`, `disk`, `ffmpeg`, `too_large`, `timeout`, `upload`, `blocked`. ترتیب بررسی مهم است (مثلاً خطای ffmpeg نباید «محتوای موجود نیست» تفسیر شود). هر خطا در لاگ job با متن اصلی ذخیره می‌شود و در پنل مدیریت قابل مشاهده است.

---

## ۳) هوش مصنوعی

- کلاینت هر سرویس سازگار با OpenAI را پشتیبانی می‌کند (`/chat/completions`), هم `stream=true` (SSE) و هم پاسخ JSON معمولی.
- تاریخچه‌ی هر کاربر در SQLite نگه‌داری می‌شود و با سقف `AI_HISTORY_MESSAGES` و `AI_HISTORY_CHARS` به مدل داده می‌شود (کنترل هزینه و context).
- تحلیل تصویر با `image_url` و پیام‌های multimodal؛ تبدیل ویس با endpoint سازگار Whisper (`AI_TRANSCRIBE=true`).
- خطاهای HTTP به پیام‌های کاربرپسند نگاشت می‌شوند: 401 → کلید نامعتبر، 429 → شلوغی، 402 → اعتبار تمام‌شده، timeout → تلاش دوباره.
- در حالت استریم، اولین chunk سریع نمایش داده می‌شود و سپس متن با ادیت دوره‌ای کامل می‌شود؛ در صورت شکست وسط استریم، متن جمع‌آوری‌شده حفظ می‌شود.

---

## ۴) داده‌ها

SQLite با `PRAGMA journal_mode=WAL`, `synchronous=NORMAL` و `busy_timeout` — برای بار یک ربات تلگرامی کاملاً کافی و بدون نیاز به سرور دیتابیس جدا.

| جدول | نقش |
| --- | --- |
| `users` | زبان، پلن، سهمیه‌ی روزانه، بن، زمان آخرین فعالیت |
| `downloads` | تاریخچه‌ی دانلودها (وضعیت، حجم، زمان، خطا) برای آمار |
| `file_cache` | `file_id` تلگرام برای ارسال فوری |
| `ai_messages` | حافظه‌ی گفتگوی هر کاربر |
| `settings` | حالت تعمیر و تنظیمات زمان اجرا |
| `pending` | توکن‌های انتخاب کیفیت/پلی‌لیست با TTL |
| `deep_links` | لینک‌های اشتراک‌گذاری‌شده (`t.me/bot?start=...`) |
| `counters` | شمارنده‌های سراسری |

نوشتن‌ها در تراکنش‌های کوتاه انجام می‌شوند و از `INSERT … ON CONFLICT` استفاده می‌شود تا race بین دو آپدیت همزمان کاربر رخ ندهد.

---

## ۵) امنیت

| ریسک | دفاع |
| --- | --- |
| SSRF روی لینک مستقیم | فقط `http/https`، resolve و رد کردن IP خصوصی/لوپ‌بک/لینک‌لوکال، محدودیت ریدایرکت |
| خستگی سرویس (spam) | throttle پیام و کال‌بک، قفل per-user، سهمیه‌ی روزانه |
| دسترسی به پنل | `AdminGuard` روی روتر ادمین + بررسی `OWNER_IDS`/`ADMIN_IDS` |
| تزریق HTML در کپشن | `esc()` روی همه‌ی ورودی‌های کاربر پیش از HTML تلگرام |
| از کار افتادن کل ربات با یک خطا | `@dp.errors()` سراسری + لاگ کامل + پاسخ محترمانه |
| نشت توکن | `.env` در `.gitignore`؛ `SecretStr` در تنظیمات؛ لاگ‌ها توکن را چاپ نمی‌کنند |

---

## ۶) کیفیت و تست

- `pytest` با ۸۴ تست: فرمت اعداد و زمان، شکستن HTML طولانی، استخراج و نرمال‌سازی URL، کیفیت‌ها، CRUD دیتابیس، پارس SSE، ساخت URL تصویر، برابری کلیدهای fa/en، طول `callback_data`، طبقه‌بندی خطا، چرخه‌ی job، تنظیمات.
- `ruff` برای lint و فرمت (`line-length = 118`).
- CI روی Python 3.11 و 3.12.

---

## ۷) نقشه‌ی توسعه‌ی آینده

- [ ] پنل وب ادمین (FastAPI + همان SQLite)
- [ ] دانلود تورنت/مگنت (با سرویس جدا)
- [ ] تولید ویدیو از متن (APIهای video)
- [ ] صف Redis برای مقیاس چند-پروسه‌ای
- [ ] Webhook به‌جای polling برای استقرارهای بزرگ
- [ ] پلن‌های اشتراک با پرداخت (Stars / درگاه)
