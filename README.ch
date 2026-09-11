<div dir="rtl">

# ⚡ idontScanner

<p align="center">
  <img src="logo.PNG" alt="idontScnner Logo" width="320">
</p>

### VPS 专业 SNI / TLS 检测与诊断面板

**idontScanner** 是一个轻量、快速且可自托管的面板，用于检查 TLS 连接状态、DNS/TCP/TLS 时间、证书、ALPN、Cipher、域名状态以及扫描历史。

> 🎯 项目目标：为**有权检查的目标**提供一个简洁可靠的**网络 / TLS 诊断工具**。
>
> 本项目不用于大范围互联网扫描、生成绕过网络限制的设置，或创建用于绕过网络过滤的实际配置。

---

## 🚀 快速安装

通过 GitHub 安装的最快方式：

```bash
curl -fsSL https://raw.githubusercontent.com/durwinam/idontScanner/main/install.sh | sudo bash
```

安装程序会自动：

- 安装 Python 和所需依赖。
- 创建独立的 Virtual Environment。
- 创建专用的 `idontscanner` 系统用户。
- 准备 SQLite 数据库。
- 要求设置管理员用户名和密码。
- 默认建议使用 `8088` 端口，如果该端口已被占用，则自动选择下一个可用端口。
- 启用 systemd 服务。
- 执行 Health Check。
- 如果启用了 UFW，则为面板端口配置规则。

### 从 ZIP 文件安装

```bash
unzip idontScanner-v2.0.0.zip
cd idontScanner-2.0.0
sudo bash install.sh --fresh
```

> `--fresh` 会删除之前的安装、数据库和旧设置。普通更新时不要使用此选项。

---

<p align="center">
  <img src="static/logo/IMG_0397.jpeg" alt="idontScanner Logo" width="420">
</p>

## 🔄 无需重新安装即可更新

安装完成后，每次版本更新都不再需要重新运行安装程序。

### 推荐方式

```bash
sudo idontScanner update
```

### 直接方式

```bash
sudo bash /opt/idontScanner/update.sh
```

更新过程会：

- 从 GitHub 下载新的源代码。
- 保留 `.env`。
- 保留 SQLite 数据库。
- 保留用户名 / 密码。
- 保留历史记录。
- 保留域名。
- 保留 Telegram 设置。
- 保留 Scheduler。
- 更新依赖。
- 执行数据库 Migration。
- 重启服务。
- 执行 Health Check。

---

## 🖥️ 管理 CLI

运行：

```bash
sudo idontScanner
```

即可访问完整的管理菜单：

| 选项 | 用途 |
|---|---|
| 🔐 Reset Password | 修改管理员密码 |
| 🌐 Panel Address | 显示面板地址 |
| 🔌 Change Port | 修改 HTTP 端口 |
| 🔄 Update | 更新且不删除信息 |
| 🤖 Telegram | 管理 Token / Owner / Admin |
| 📊 Status | 查看服务状态 |
| 📜 Logs | 查看日志 |
| ♻️ Restart | 重启 + Health Check |
| 🧹 System Info | 查看安装和系统信息 |

### 直接命令

```bash
sudo idontScanner update
sudo idontScanner status
sudo idontScanner restart
sudo idontScanner logs
sudo idontScanner version
sudo idontScanner help
```

---

## 🔍 扫描器

### 🌐 Domain Scanner

对活动域名进行 TLS 扫描并显示：

- 状态
- 延迟
- DNS Time
- TCP Time
- TLS Handshake
- TLS Version
- ALPN
- Cipher
- IP
- 证书
- 签发者
- 到期时间
- SAN

Scanner 的标准 TLS 端口为 **443**，并且在内部与 Host 分开保存，因此 SNI 始终保持为纯 hostname。

### 🎯 SNI / TLS Check

检查指定目标和 SNI 的 TLS 行为，不改变标准 HTTPS 连接逻辑。

### ☁️ CDN Diagnostics

检查指定 Endpoint，并显示连接信息和 Provider Hint，用于 CDN 诊断。

### ⚡ Connection Tester

Connection Tester 会自动识别由 Xray 兼容面板生成的配置，并支持以下格式进行 Endpoint 检测：

- VLESS
- VMess
- Trojan
- Shadowsocks
- Hysteria2
- WireGuard `.conf`

对于 TCP/TLS 配置，会在 Endpoint 层面检查：

- Host / Port
- Protocol / Transport
- Security / SNI
- DNS / TCP / TLS timing
- TLS Version
- ALPN
- Cipher
- Destination IP

对于 Hysteria2、Shadowsocks 和 WireGuard 等 UDP/QUIC 协议，程序不会将 TCP 连接报告为协议成功，只显示相关的 Endpoint/DNS 信息。

同时也会直接从 VPS 本身测试 Instagram / YouTube / Telegram 的访问情况，不会使用输入的配置来路由这些服务的流量。

> UUID、密码、auth 和私钥不会显示在输出中，并且配置不会被永久保存。

---

## 📡 服务诊断

以下服务会从 VPS 本身进行 Reachability 检测：

- Instagram
- YouTube
- Telegram

每个服务都会进行多次尝试，并报告以下指标：

- DNS
- TCP
- TLS
- HTTP Response
- Min
- Max
- Average
- Jitter
- HTTP Status

这些数值表示 **VPS → 服务 Endpoint 的延迟**，不应被理解为服务实际的整体运行速度。

---

## 🤖 Telegram Bot

Telegram 是可选功能，并通过 **Polling** 工作，因此使用 Bot 不需要将面板放置在 HTTPS 或 Webhook 后面。

设置位置：

**Settings → Telegram Bot**

可用设置：

- Bot Token
- Owner Telegram ID
- 多个 Admin Telegram ID

只有已注册的 Owner 和 Admin 才可以使用 Bot。

### 命令

```text
/start
/menu
/scan
/status
```

<p align="center">
  <img src="static/logo/IMG_0399.jpeg" alt="idontScanner" width="420">
</p>

---

## ⏱ Scheduler

Scheduler 默认关闭，其设置会保存在 SQLite 中。

可用间隔：

```text
30 分钟
1 小时
1.5 小时
2 小时
3 小时
6 小时
12 小时
24 小时
```

你也可以选择发送所有扫描结果，或者仅发送需要关注的结果。

---

## 🔐 安全性

- 密码不会以明文形式存储。
- 密码哈希使用 Salt 和 `scrypt` 生成。
- Session 使用独立的 Secret 进行签名。
- Mutation API 具有 CSRF 防护。
- 服务使用独立的 `idontscanner` 用户运行。
- Systemd 使用 `NoNewPrivileges` 和文件限制。
- 域名输入会按照 hostname 进行验证。
- SQLite 数据存储在应用源代码目录之外。
- 更新不会删除本地信息。

---

## 🗂️ 项目结构

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

项目代码采用模块化结构维护，使 Scanner、Database、Authentication、Telegram 和 Scheduler 相互分离，而不是全部放在一个大型文件中，从而更容易进行开发和维护。

---

## 🛠️ 服务管理

```bash
sudo systemctl status idontscanner
sudo systemctl restart idontscanner
sudo journalctl -u idontscanner -f
```

---

## 🧹 完全全新安装

如果你确实希望删除所有之前的信息：

```bash
sudo bash install.sh --fresh
```

⚠️ 此模式会删除数据库、历史记录、域名、Telegram、Scheduler 以及之前的用户账户。

<p align="center">
  <img src="static/logo/IMG_0398.jpeg" alt="idontScanner" width="420">
</p>

---

## 📌 GitHub

项目主仓库：

**https://github.com/durwinam/idontScanner**

从 GitHub 直接安装：

```bash
curl -fsSL https://raw.githubusercontent.com/durwinam/idontScanner/main/install.sh | sudo bash
```

---

## 📦 版本

**v2.0.0**

---

## 📄 许可证

MIT License — Copyright © 2026 **durwinam**

</div>
