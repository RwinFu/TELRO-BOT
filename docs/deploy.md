# 🚀 راهنمای استقرار TELRO

این سند سه مسیر استقرار را پوشش می‌دهد: **systemd** (ساده‌ترین روی VPS)، **Docker** (تمیزترین)، و **Bot API محلی** (برای آپلود تا ۲ گیگابایت).

---

## ۱) پیش‌نیازها

| مورد | حداقل | پیشنهاد |
| --- | --- | --- |
| سیستم عامل | Ubuntu 22.04 / Debian 12 | Ubuntu 24.04 |
| CPU | ۱ هسته | ۲ هسته |
| RAM | ۱ گیگابایت | ۲ گیگابایت |
| دیسک | ۱۰ گیگابایت | ۴۰ گیگابایت SSD |
| پایتون | 3.11 | 3.12 |
| نرم‌افزار | `ffmpeg`, `curl` | `deno` (برای امضای یوتیوب) |

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg curl git
```

> **Deno** را نصب کنید اگر یوتیوب خطای «nsig» می‌دهد: `curl -fsSL https://deno.land/install.sh | sh` و سپس `DENO_INSTALL` را به سرویس اضافه کنید. در Docker این کار از قبل انجام شده است.

---

## ۲) استقرار با systemd

```bash
# کاربر غیرروت
sudo adduser --disabled-password --gecos "" telro
sudo su - telro

git clone https://github.com/RwinFu/TELRO-BOT.git
cd TELRO-BOT
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt

cp .env.example .env
nano .env        # BOT_TOKEN, OWNER_IDS, SUPPORT_USERNAME
```

تست اولیه:

```bash
.venv/bin/python -m bot
# Ctrl+C برای خروج
```

سرویس:

```bash
sudo tee /etc/systemd/system/telro.service > /dev/null <<'EOF'
[Unit]
Description=TELRO Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=telro
Group=telro
WorkingDirectory=/home/telro/TELRO-BOT
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/telro/TELRO-BOT/.venv/bin/python -m bot
Restart=always
RestartSec=5
TimeoutStopSec=30

# امنیت
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/home/telro/TELRO-BOT/data

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now telro
sudo systemctl status telro
sudo journalctl -u telro -f        # لاگ زنده
```

> اگر پوشه‌ی خانه را `read-only` گذاشتید، مطمئن شوید `ReadWritePaths` دقیقاً به `data` اشاره می‌کند و `DB_PATH`, `DOWNLOAD_DIR`, `GENERATED_DIR` هم داخل همان هستند.

---

## ۳) استقرار با Docker

```bash
cp .env.example .env
nano .env
docker compose up -d --build
docker compose logs -f bot
```

- دیتابیس و فایل‌های موقت در `./data` مانت می‌شوند (پایدار بین آپدیت‌ها).
- اگر فایل کوکی اینستاگرام دارید، `cookies.txt` را کنار `docker-compose.yml` بگذارید.
- پورت `8080` روی هاست باز می‌شود؛ می‌توانید آن را با فایروال فقط به IP مانیتور محدود کنید یا در `.env` مقدار `HEALTH_PORT` را تغییر دهید.

آپدیت:

```bash
git pull
docker compose up -d --build
```

پاک‌سازی کامل (داده‌ها باقی می‌مانند):

```bash
docker compose down
```

---

## ۴) آپلود ۲ گیگابایتی (Bot API محلی)

تلگرام با API ابری سقف آپلود ربات را **۵۰ مگابایت** گذاشته است. با اجرای [telegram-bot-api](https://github.com/tdlib/telegram-bot-api) روی سرور خودتان، این سقف **۲ گیگابایت** می‌شود (سقف واقعی فایل‌ها).

### الف) گرفتن API ID و Hash

1. به <https://my.telegram.org> بروید → `API development tools`
2. یک اپ بسازید؛ `api_id` و `api_hash` را بردارید.

### ب) اجرا با Docker (ساده‌ترین)

در `.env` اضافه کنید:

```env
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
```

در `docker-compose.yml` بخش `bot` را از حالت کامنت خارج کنید:

```yaml
  bot:
    environment:
      TELEGRAM_API_SERVER: http://telegram-bot-api:8081
```

سپس:

```bash
docker compose --profile local-api up -d --build
```

### ج) اجرا روی هاست (بدون Docker)

```bash
sudo apt install -y build-essential cmake gperf libssl-dev zlib1g-dev
git clone --recursive https://github.com/tdlib/telegram-bot-api.git
cd telegram-bot-api && mkdir build && cd build
cmake -DCMAKE_BUILD_TYPE=Release ..
cmake --build . -j$(nproc)

sudo mkdir -p /var/lib/telegram-bot-api
sudo ./telegram-bot-api \
  --api-id=1234567 \
  --api-hash=0123456789abcdef0123456789abcdef \
  --local \
  --http-port=8081 \
  --dir=/var/lib/telegram-bot-api
```

در `.env` ربات:

```env
TELEGRAM_API_SERVER=http://127.0.0.1:8081
```

ری‌استارت ربات. حالا `MAX_UPLOAD_MB=0` را روی خودکار بگذارید تا سقف ۲۰۰۰ مگ فعال شود، یا مقدار دلخواه بدهید.

> **نکته:** فایل‌هایی که با API محلی ارسال می‌شوند به‌صورت موقت روی دیسک سرور هستند؛ مطمئن شوید `data/` فضای کافی دارد و `cleanup` دوره‌ای فعال است.

---

## ۵) Nginx و دامنه (اختیاری)

فقط برای `/health` و مانیتورینگ بیرونی لازم است:

```nginx
server {
    listen 80;
    server_name health.example.com;

    location /health {
        proxy_pass http://127.0.0.1:8080/health;
        access_log off;
    }

    location / {
        return 404;
    }
}
```

```bash
sudo certbot --nginx -d health.example.com
```

سپس در UptimeRobot یک HTTP monitor روی `https://health.example.com/health` بسازید.

---

## ۶) بکاپ و نگهداری

**بکاپ دیتابیس (SQLite در حالت WAL):**

```bash
mkdir -p ~/backups
sqlite3 ~/TELRO-BOT/data/telro.db ".backup '$HOME/backups/telro-$(date +%F).db'"
find ~/backups -name 'telro-*.db' -mtime +14 -delete
```

> از `cp` روی دیتابیس در حال اجرا خودداری کنید. اگر `sqlite3` نصب نیست: `sudo apt install sqlite3`.

**cron پیشنهادی:**

```cron
0 4 * * * sqlite3 /home/telro/TELRO-BOT/data/telro.db ".backup '/home/telro/backups/telro-$(date +\%F).db'" && find /home/telro/backups -name 'telro-*.db' -mtime +14 -delete
0 5 * * * find /home/telro/TELRO-BOT/data/downloads -type f -mmin +180 -delete
```

ربات خودش هر ۳۰ دقیقه فایل‌های موقت و کش منقضی را پاک می‌کند؛ cron یک لایه‌ی اطمینان اضافه است.

**مانیتورینگ:**

- `/admin` → آمار زنده، کاربران، کش، بن و اشتراک
- `journalctl -u telro -n 200` یا `docker compose logs --tail=200 bot`
- `curl -s localhost:8080/health`

---

## ۷) رفع مشکلات رایج

| نشانه | علت محتمل | راه‌حل |
| --- | --- | --- |
| `TelegramUnauthorizedError` | توکن اشتباه / revoke شده | توکن را از BotFather دوباره بگیرید |
| `Conflict: terminated by other getUpdates` | دو نسخه همزمان در حال اجراست | سرویس/کانتینر تکراری را ببندید. Webhook را با `deleteWebhook` پاک کنید |
| MP3 ساخته نمی‌شود | ffmpeg نصب نیست | `ffmpeg -version` را چک کنید؛ `sudo apt install ffmpeg` |
| «این محتوا در دسترس نیست» برای یوتیوب | IP دیتاسنتر بلاک شده | پروکسی (`PROXY=socks5://...`) یا `cookies.txt` |
| اینستاگرام خطای login | محتوای خصوصی | `COOKIES_FILE` را تنظیم کنید |
| فایل بالای ۵۰ مگ ارسال نمی‌شود | API ابری | بخش ۴: Bot API محلی |
| AI پاسخ نمی‌دهد | سرویس رایگان شلوغ است | `AI_BASE_URL` را به ارائه‌دهنده‌ی دیگر تغییر دهید |
| ربات در گروه کار نمی‌کند | پیش‌فرض خاموش است | `ENABLE_GROUPS=true` + دسترسی admin در گروه |
| `/admin` باز نمی‌شود | `OWNER_IDS` خالی است | `/id` بفرستید و آیدی را در `.env` بگذارید |

---

## ۸) چک‌لیست قبل از تحویل به کاربران

- [ ] `BOT_TOKEN` در `.env` و `.env` در `.gitignore`
- [ ] `OWNER_IDS` تنظیم و `/admin` تست شده
- [ ] `FORCE_JOIN_CHANNELS` و دکمه‌ی «بررسی عضویت» تست شده
- [ ] `SUPPORT_USERNAME` برای دکمه‌ی پشتیبانی تنظیم شده
- [ ] Download از یوتیوب، اینستاگرام، تیک‌تاک و یک لینک مستقیم تست شده
- [ ] MP3 و کیفیت‌های مختلف روی ffmpeg تست شده
- [ ] AI چت، تحلیل عکس، تصویرساز تست شده
- [ ] `/health` از بیرون پاسخ می‌دهد
- [ ] بکاپ خودکار دیتابیس فعال است
- [ ] سرویس با `Restart=always` (systemd) یا `restart: unless-stopped` (Docker) بالا می‌آید
