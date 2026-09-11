<div dir="rtl">

# ⚡ idontScanner

<p align="center">
  <img src="logo.PNG" alt="idontScnner Logo" width="320">
</p>

### پنل حرفه‌ای تشخیص و عیب‌یابی SNI / TLS برای VPS

**idontScanner** یک پنل سبک، سریع و Self-Hosted برای بررسی وضعیت اتصال TLS، زمان DNS/TCP/TLS، گواهی، ALPN، Cipher، وضعیت دامنه‌ها و تاریخچه‌ی اسکن است.

> 🎯 هدف پروژه: ارائه‌ی یک ابزار تمیز و قابل‌اعتماد برای **Network / TLS Diagnostics روی Targetهایی که مجاز به بررسی آن‌ها هستید**.
>
> این پروژه برای اسکن اینترنت به‌صورت گسترده، تولید تنظیمات دورزدن محدودیت شبکه یا ساخت کانفیگ عملیاتی برای عبور از فیلترینگ طراحی نشده است.

---

## 🚀 نصب سریع

 روی GitHub سریع‌ترین روش نصب:

```bash
curl -fsSL https://raw.githubusercontent.com/durwinam/idontScanner/main/install.sh | sudo bash
```

نصب‌کننده به‌صورت خودکار:

- Python و وابستگی‌های لازم را نصب می‌کند.
- Virtual Environment اختصاصی می‌سازد.
- کاربر سیستمی `idontscanner` ایجاد می‌کند.
- دیتابیس SQLite را آماده می‌کند.
- Username و Password ادمین را از شما می‌گیرد.
- پورت `8088` را پیشنهاد می‌دهد و در صورت اشغال بودن، پورت آزاد بعدی را انتخاب می‌کند.
- سرویس systemd را فعال می‌کند.
- Health Check انجام می‌دهد.
- در صورت فعال بودن UFW، Rule مربوط به پورت پنل را تنظیم می‌کند.

### نصب از فایل ZIP

```bash
unzip idontScanner-v2.0.0.zip
cd idontScanner-2.0.0
sudo bash install.sh --fresh
```

> `--fresh` نصب قبلی، دیتابیس و تنظیمات قبلی را حذف می‌کند. برای Update معمولی از این گزینه استفاده نکنید.

---

## 🔄 Update بدون نصب مجدد

بعد از نصب، دیگر لازم نیست برای هر نسخه دوباره Installer را اجرا کنید.

### روش پیشنهادی

```bash
sudo idontScanner update
```

### روش مستقیم

```bash
sudo bash /opt/idontScanner/update.sh
```

Update:

- سورس جدید را از GitHub دریافت می‌کند.
- `.env` را حفظ می‌کند.
- SQLite Database را حفظ می‌کند.
- Username / Password را حفظ می‌کند.
- History را حفظ می‌کند.
- Domainها را حفظ می‌کند.
- تنظیمات Telegram را حفظ می‌کند.
- Scheduler را حفظ می‌کند.
- Dependencyها را به‌روزرسانی می‌کند.
- Migration دیتابیس را اجرا می‌کند.
- سرویس را Restart می‌کند.
- Health Check انجام می‌دهد.

---

## 🖥️ CLI مدیریت

با اجرای:

```bash
sudo idontScanner
```

یک منوی مدیریتی کامل در اختیار شما قرار می‌گیرد:

| گزینه | کاربرد |
|---|---|
| 🔐 Reset Password | تغییر رمز ادمین |
| 🌐 Panel Address | نمایش آدرس پنل |
| 🔌 Change Port | تغییر پورت HTTP |
| 🔄 Update | آپدیت بدون حذف اطلاعات |
| 🤖 Telegram | مدیریت Token / Owner / Admin |
| 📊 Status | وضعیت سرویس |
| 📜 Logs | مشاهده لاگ‌ها |
| ♻️ Restart | Restart + Health Check |
| 🧹 System Info | اطلاعات نصب و سیستم |

### دستورات مستقیم

```bash
sudo idontScanner update
sudo idontScanner status
sudo idontScanner restart
sudo idontScanner logs
sudo idontScanner version
sudo idontScanner help
```

---

## 🔍 Scannerها

### 🌐 Domain Scanner

اسکن TLS دامنه‌های فعال و نمایش:

- Status
- Latency
- DNS Time
- TCP Time
- TLS Handshake
- TLS Version
- ALPN
- Cipher
- IP
- Certificate
- Issuer
- Expiration
- SAN

پورت استاندارد TLS در Scanner برابر **443** است و به شکل داخلی از Host جدا نگه داشته می‌شود؛ بنابراین SNI همیشه hostname خالص باقی می‌ماند.

### 🎯 SNI / TLS Check

بررسی رفتار TLS برای یک Target و SNI مشخص، بدون تغییر دادن منطق اتصال استاندارد HTTPS.

### ☁️ CDN Diagnostics

بررسی یک Endpoint مشخص و نمایش اطلاعات اتصال و Provider Hint برای تشخیص‌های CDN.

### ⚡ Connection Tester
Connection Tester کانفیگ‌های تولیدشده توسط پنل‌های Xray-compatible را به‌صورت خودکار تشخیص می‌دهد و برای تشخیص Endpoint از این فرمت‌ها پشتیبانی می‌کند:

- VLESS
- VMess
- Trojan
- Shadowsocks
- Hysteria2
- WireGuard `.conf`

برای کانفیگ‌های دارای TCP/TLS، اطلاعات زیر در سطح Endpoint بررسی می‌شود:

- Host / Port
- Protocol / Transport
- Security / SNI
- DNS / TCP / TLS timing
- TLS Version
- ALPN
- Cipher
- IP مقصد

برای پروتکل‌های UDP/QUIC مثل Hysteria2، Shadowsocks و WireGuard، برنامه اتصال TCP را به‌عنوان موفقیت پروتکل گزارش نمی‌کند و فقط اطلاعات Endpoint/DNS مربوط را نمایش می‌دهد.

تست مستقیم دسترسی به Instagram / YouTube / Telegram نیز از خود VPS انجام می‌شود و از کانفیگ واردشده برای Route کردن ترافیک سرویس‌ها استفاده نمی‌شود.

> UUID، پسورد، auth و private key در خروجی نمایش داده نمی‌شوند و کانفیگ برای ذخیره‌سازی دائمی نگهداری نمی‌شود.

---

## 📡 Service Diagnostics

برای تشخیص Reachability از خود VPS، سرویس‌های زیر تست می‌شوند:

- Instagram
- YouTube
- Telegram

هر سرویس با چند Attempt بررسی شده و معیارهای زیر گزارش می‌شوند:

- DNS
- TCP
- TLS
- HTTP Response
- Min
- Max
- Average
- Jitter
- HTTP Status

این اعداد **Latency مسیر VPS → Service Endpoint** هستند و نباید به‌عنوان سرعت واقعی کل سرویس تفسیر شوند.

---

## 🤖 Telegram Bot

Telegram اختیاری است و با **Polling** کار می‌کند؛ بنابراین برای استفاده از Bot لازم نیست پنل را روی HTTPS یا Webhook قرار دهید.

تنظیمات از داخل:

**Settings → Telegram Bot**

قابل انجام است:

- Bot Token
- Owner Telegram ID
- چند Admin Telegram ID

فقط Owner و Adminهای ثبت‌شده اجازه استفاده از Bot را دارند.

### دستورات

```text
/start
/menu
/scan
/status
```

---

## ⏱ Scheduler

Scheduler به‌صورت پیش‌فرض خاموش است و تنظیماتش داخل SQLite باقی می‌ماند.

بازه‌های قابل انتخاب:

```text
30 دقیقه
1 ساعت
1.5 ساعت
2 ساعت
3 ساعت
6 ساعت
12 ساعت
24 ساعت
```

امکان ارسال نتیجه همه Scanها یا فقط نتایجی که نیاز به توجه دارند نیز وجود دارد.

---

## 🔐 امنیت

- Passwordها به‌صورت Plaintext ذخیره نمی‌شوند.
- Password Hash با Salt و `scrypt` تولید می‌شود.
- Sessionها با Secret جداگانه امضا می‌شوند.
- Mutation APIها دارای CSRF protection هستند.
- سرویس با User اختصاصی `idontscanner` اجرا می‌شود.
- Systemd با `NoNewPrivileges` و محدودیت‌های فایل اجرا می‌شود.
- ورودی Domain به‌عنوان hostname اعتبارسنجی می‌شود.
- داده‌های SQLite خارج از Application Source نگهداری می‌شوند.
- Update اطلاعات محلی را حذف نمی‌کند.

---

## 🗂️ ساختار پروژه

```text
idontScanner-2.0.0/
├── app/
│   ├── auth.py
│   ├── config.py
│   ├── connection.py
│   ├── database.py
│   ├── main.py
│   ├── scanner.py
│   ├── scheduler.py
│   ├── security.py
│   └── telegram.py
│
├── static/
├── templates/
├── systemd/
├── install.sh
├── update.sh
├── idontscanner-cli
├── requirements.txt
├── VERSION
└── LICENSE
```

کد پروژه به‌صورت ماژولار نگهداری شده تا Scanner، Database، Authentication، Telegram و Scheduler از یک فایل بزرگ جدا باشند و توسعه و نگهداری آن ساده‌تر شود.

---

## 🛠️ مدیریت سرویس

```bash
sudo systemctl status idontscanner
sudo systemctl restart idontscanner
sudo journalctl -u idontscanner -f
```

---

## 🧹 نصب کاملاً Fresh

اگر واقعاً می‌خواهید تمام اطلاعات قبلی حذف شود:

```bash
sudo bash install.sh --fresh
```

⚠️ این حالت دیتابیس، History، Domainها، Telegram، Scheduler و حساب کاربری قبلی را حذف می‌کند.

---

## 📌 GitHub

مخزن اصلی پروژه:

**https://github.com/durwinam/idontScanner**

نصب مستقیم از GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/durwinam/idontScanner/main/install.sh | sudo bash
```

---

## 📦 Version

**v2.0.0**

---

## 📄 License

MIT License — Copyright © 2026 **durwinam**

</div>
