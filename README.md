# 🛡️ idontScanner

### 🔍 اسکنر SNI / TLS برای بررسی اتصال و پیدا کردن Endpointهای سالم و سریع

`idontScanner` یک ابزار سبک، مستقل و Self-Hosted برای VPS است که از روی همان سرور، اتصال TLS به لیستی کنترل‌شده از دامنه‌ها را بررسی می‌کند و نتیجه را با تمرکز روی **وضعیت اتصال، Latency و اطلاعات TLS** نمایش می‌دهد.

پنل وب پروژه با رابط **Dark / Glass / Neon** طراحی شده و برای استفاده روی دسکتاپ و موبایل بهینه شده است.

---

## ⚡ قابلیت‌های اصلی

| قابلیت | توضیح |
|---|---|
| 🔐 **احراز هویت پنل** | ورود امن با نام کاربری و رمز عبور مدیر |
| 🛡️ **Scrypt Password Hashing** | ذخیره رمز عبور به‌صورت Hash با Scrypt |
| 🔒 **CSRF Protection** | محافظت درخواست‌های حساس در برابر CSRF |
| 🌐 **SNI / TLS Scanner** | بررسی اتصال TLS به دامنه‌های تعریف‌شده |
| ⚡ **Latency Measurement** | اندازه‌گیری زمان برقراری TLS Handshake |
| 🔐 **TLS Version** | نمایش نسخه TLS مورد استفاده در اتصال موفق |
| 📜 **Certificate Subject** | دریافت Subject گواهی TLS مقصد |
| 🚦 **Connection Status** | تشخیص وضعیت‌هایی مانند ONLINE، TIMEOUT، TLS ERROR و FAILED |
| 🚀 **Concurrent Scanning** | اجرای هم‌زمان اسکن‌ها با کنترل Concurrency |
| 🔎 **جستجوی دامنه‌ها** | فیلتر سریع Targetها از داخل پنل |
| ➕ **Custom Domains** | افزودن دامنه اختصاصی به لیست اسکن |
| 🗑️ **مدیریت Targetها** | حذف دامنه‌های سفارشی از پنل |
| 📊 **Scan Statistics** | نمایش تعداد Targetها، سالم‌ها، بهترین Latency و زمان اسکن |
| 🕘 **Scan History** | نگهداری و نمایش ۲۰ اسکن اخیر |
| 💾 **SQLite Storage** | ذخیره اطلاعات بدون نیاز به دیتابیس خارجی |
| 🖥️ **Web Panel** | داشبورد سبک و Responsive برای مدیریت Scanner |
| 📱 **Mobile Friendly** | نمایش مناسب روی موبایل و دسکتاپ |
| 🎨 **Dark Glass UI** | رابط مدرن با افکت Glass و Neon |
| 🐧 **Systemd Service** | اجرای دائمی سرویس به‌صورت Systemd |
| 🔧 **Auto Port Detection** | انتخاب خودکار پورت آزاد در صورت اشغال بودن پورت پیش‌فرض |
| 🧱 **Hardened Service** | اجرای سرویس با کاربر اختصاصی و محدودیت‌های Systemd |
| 🔥 **UFW Integration** | باز کردن خودکار پورت در صورت فعال بودن UFW |
| 🧩 **Isolated Python Environment** | نصب وابستگی‌ها داخل Virtual Environment اختصاصی |

---

## 🎯 نحوه عملکرد Scanner

`idontScanner` یک لیست کنترل‌شده از دامنه‌ها را از VPS اجراکننده بررسی می‌کند.

برای هر Target:

1. اتصال به پورت `443` برقرار می‌شود.
2. TLS Handshake انجام می‌شود.
3. زمان برقراری اتصال اندازه‌گیری می‌شود.
4. نسخه TLS استخراج می‌شود.
5. Subject گواهی دریافت می‌شود.
6. نتیجه با وضعیت مناسب در پنل نمایش داده می‌شود.
7. نتایج اسکن در SQLite ذخیره می‌شوند.

اسکن‌ها به‌صورت هم‌زمان و با **حداکثر ۸ اتصال فعال** اجرا می‌شوند تا فشار غیرضروری روی سرور ایجاد نشود.

> محدودیت فعلی هر Batch برابر **۱۰۰ دامنه فعال** است.

---

## 🌐 Targetهای پیش‌فرض

پروژه در اولین اجرا مجموعه‌ای از Targetهای آماده را در اختیار شما قرار می‌دهد، از جمله:

- Cloudflare
- Google
- Bing
- Yahoo
- Apple
- App Store
- iCloud
- Google Play
- GitHub
- GitLab
- Microsoft
- Microsoft Live
- Office
- Azure
- Amazon
- Netflix
- Spotify
- Discord
- Telegram
- WhatsApp
- Reddit
- Wikipedia
- Archive
- Fastly
- Akamai
- Google APIs
- Gstatic
- Googleusercontent
- Aparat
- Digikala
- Divar
- Snapp
- Irancell
- MCI

دامنه‌های سفارشی نیز از داخل پنل قابل اضافه‌کردن هستند.

---

## 🖥️ Web Panel

داشبورد شامل بخش‌های اصلی زیر است:

### 📊 آمار اسکن

- **Targets** — تعداد دامنه‌های فعال
- **Healthy** — تعداد اتصال‌های TLS موفق
- **Best Latency** — سریع‌ترین Target موفق
- **Scan Time** — مدت زمان اجرای Batch

### 📋 Target List

برای هر دامنه موارد زیر نمایش داده می‌شود:

- نام Target
- Domain
- وضعیت اتصال
- Latency
- TLS Version
- گزینه حذف برای دامنه‌های سفارشی

### 🔎 Search

با استفاده از Search می‌توانید Target موردنظر را سریعاً از لیست پیدا کنید.

### ➕ Add Domain

امکان افزودن دامنه اختصاصی وجود دارد.

فقط **Domain Name** پذیرفته می‌شود و موارد زیر مجاز نیستند:

- URL
- IP Address
- مسیر `/`
- `@`
- دامنه نامعتبر

---

## 🕘 Scan History

نتایج Batchهای قبلی در SQLite ذخیره می‌شوند و پنل **۲۰ اسکن اخیر** را نمایش می‌دهد.

برای هر اسکن:

- شماره اسکن
- زمان اجرا
- تعداد Targetهای سالم
- تعداد کل Targetها
- مدت اجرای اسکن

نمایش داده می‌شود.

---

## 🔐 امنیت

امنیت یکی از بخش‌های اصلی پروژه است:

- Session Authentication
- CSRF Protection
- Scrypt Password Hashing
- Secure Random Secret
- Security Headers
- `X-Content-Type-Options`
- `X-Frame-Options`
- `Referrer-Policy`
- `Permissions-Policy`
- اجرای سرویس با User اختصاصی
- `NoNewPrivileges`
- `PrivateTmp`
- `ProtectSystem=strict`
- `ProtectHome`
- محدودسازی مسیرهای قابل نوشتن
- محدودیت Concurrency در Scanner
- اعتبارسنجی Domain قبل از Scan

> برای استفاده عمومی، بهتر است پنل HTTP پشت یک Reverse Proxy با HTTPS قرار بگیرد و دسترسی مستقیم به پورت برنامه محدود شود.

---

## 📦 نصب

پس از Extract کردن پروژه روی VPS:

```bash
cd idontScanner
chmod +x install.sh
sudo ./install.sh
```

Installer به‌صورت خودکار:

- سیستم‌عامل را بررسی می‌کند.
- Python و وابستگی‌های لازم را نصب می‌کند.
- Virtual Environment می‌سازد.
- User اختصاصی `idontscanner` ایجاد می‌کند.
- Secret امن تولید می‌کند.
- رمز مدیر را به‌صورت Scrypt ذخیره می‌کند.
- SQLite Database را آماده می‌کند.
- سرویس Systemd را نصب می‌کند.
- سرویس را اجرا می‌کند.
- وضعیت سرویس و HTTP را بررسی می‌کند.
- در صورت فعال بودن UFW، Rule مربوط به پورت را اضافه می‌کند.

---

## 🔌 پورت

پورت پیش‌فرض:

```text
8088/tcp
```

اگر این پورت در حال استفاده باشد، Installer به‌صورت خودکار پورت بعدی آزاد را انتخاب می‌کند.

امکان تعیین پورت دلخواه نیز وجود دارد:

```bash
sudo ./install.sh --port 18080
```

برای جلوگیری از تغییر Rule فایروال:

```bash
sudo ./install.sh --no-ufw
```

برای نصب مجدد و حذف کامل داده‌های قبلی:

```bash
sudo ./install.sh --fresh
```

> گزینه `--fresh` داده‌های محلی، Database و تنظیمات نصب قبلی را حذف می‌کند.

---

## ⚙️ مدیریت سرویس

مشاهده وضعیت:

```bash
systemctl status idontscanner
```

Restart:

```bash
systemctl restart idontscanner
```

Stop:

```bash
systemctl stop idontscanner
```

مشاهده Log زنده:

```bash
journalctl -u idontscanner -f
```

---

## 🗂️ ساختار پروژه

```text
idontScanner/
├── app/
│   └── main.py
├── static/
│   ├── app.css
│   └── app.js
├── templates/
│   ├── login.html
│   └── dashboard.html
├── systemd/
│   └── idontscanner.service
├── .env.example
├── install.sh
├── requirements.txt
├── VERSION
├── LICENSE
└── README.md
```

---

## 🧰 تکنولوژی‌ها

- Python 3
- FastAPI
- Uvicorn
- Jinja2
- SQLite
- HTML / CSS / JavaScript
- Systemd
- OpenSSL / Python SSL

هیچ دیتابیس خارجی یا Framework سنگین دیگری برای اجرای پروژه الزامی نیست.

---

## 📍 مسیرهای اصلی

```text
/
/login/
/logout/
/dashboard/

/api/scan
/api/history
/api/domains
/api/domains/{domain_id}

/static/
```

---

## 📌 مشخصات نسخه

```text
VERSION   v1.0.0
PYTHON    3.x
DATABASE  SQLite
PANEL     Web Panel
PROTOCOL  HTTP
LICENSE   MIT
```

---

## 👤 توسعه‌دهنده

**Durwinam / idontScanner**

Repository:

```text
durwinam/idontScanner
```

---

## 📄 License

این پروژه تحت **MIT License** منتشر شده است.

Copyright © 2026 Durwinam / idontScanner contributors.
