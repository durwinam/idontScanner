"""Application configuration and immutable defaults."""

import os
import secrets
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# Load the local .env when the app is started outside systemd as well. This
# keeps the SessionMiddleware secret stable across manual starts/restarts.
_ENV_FILE = BASE / ".env"
if _ENV_FILE.exists():
    try:
        for _line in _ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _value = _line.split("=", 1)
            _key = _key.strip()
            _value = _value.strip().strip('"').strip("'")
            if _key and _key not in os.environ:
                os.environ[_key] = _value
    except OSError:
        pass

DATA_DIR = Path(os.getenv("IDONTSCANNER_DATA_DIR", str(BASE / "data")))
DB_PATH = DATA_DIR / "idontscanner.db"
BASE_PATH = ""
TIMEOUT = float(os.getenv("IDONTSCANNER_TIMEOUT", "4.0"))
SECRET = os.getenv("IDONTSCANNER_SECRET", "")
if len(SECRET) < 32:
    SECRET = secrets.token_urlsafe(48)

DEFAULT_PORT = 443
APP_VERSION = (
    (BASE / "VERSION").read_text(encoding="utf-8").strip()
    if (BASE / "VERSION").exists()
    else "v4.0.0"
)
UPDATE_VERSION_URL = "https://raw.githubusercontent.com/durwinam/idontScanner/main/VERSION"

DEFAULT_DOMAINS = [
    ("Cloudflare", "cloudflare.com", "Cloud"),
    ("Google", "google.com", "Google"),
    ("Bing", "bing.com", "Microsoft"),
    ("Yahoo", "yahoo.com", "Cloud"),
    ("Apple", "apple.com", "Apple"),
    ("App Store", "apps.apple.com", "Apple"),
    ("iCloud", "icloud.com", "Apple"),
    ("Google Play", "play.google.com", "Google"),
    ("GitHub", "github.com", "Developer"),
    ("GitLab", "gitlab.com", "Developer"),
    ("Microsoft", "microsoft.com", "Microsoft"),
    ("Microsoft Live", "live.com", "Microsoft"),
    ("Office", "office.com", "Microsoft"),
    ("Azure", "azure.com", "Microsoft"),
    ("Amazon", "amazon.com", "Cloud"),
    ("Netflix", "netflix.com", "Media"),
    ("Spotify", "spotify.com", "Media"),
    ("Discord", "discord.com", "Social"),
    ("Telegram", "telegram.org", "Social"),
    ("WhatsApp", "whatsapp.com", "Social"),
    ("Reddit", "reddit.com", "Social"),
    ("Wikipedia", "wikipedia.org", "Reference"),
    ("Archive", "archive.org", "Reference"),
    ("Fastly", "fastly.com", "CDN"),
    ("Akamai", "akamai.com", "CDN"),
    ("Google APIs", "googleapis.com", "Google"),
    ("Gstatic", "gstatic.com", "Google"),
    ("Googleusercontent", "googleusercontent.com", "Google"),
    ("Aparat", "aparat.com", "Iran"),
    ("Digikala", "digikala.com", "Iran"),
    ("Divar", "divar.ir", "Iran"),
    ("Snapp", "snapp.ir", "Iran"),
    ("Irancell", "irancell.ir", "Iran"),
    ("MCI", "mci.ir", "Iran"),
    ("HoYoverse FastCDN", "fastcdn.hoyoverse.com", "CDN"),
    ("JetBrains", "jetbrains.com", "Developer"),
    ("ArvanCloud", "www.arvancloud.ir", "Iran"),
    ("Fastly Purple Retro Wave", "purple-retro-wave.global.ssl.fastly.net", "CDN"),
    ("WordPress", "wordpress.org", "Developer"),
    ("Google Play Apps Features", "play-apps-features.googleusercontent.com", "Google"),
    ("Fastly RT Work", "rt-work.global.ssl.fastly.net", "CDN"),
    ("OpenAI", "openai.com", "AI"),
    ("ChatGPT", "chatgpt.com", "AI"),
    ("Anthropic", "anthropic.com", "AI"),
    ("Claude", "claude.ai", "AI"),
    ("X", "x.com", "Social"),
    ("Facebook", "facebook.com", "Social"),
    ("Instagram", "instagram.com", "Social"),
    ("YouTube", "youtube.com", "Media"),
    ("TikTok", "tiktok.com", "Media"),
    ("LinkedIn", "linkedin.com", "Social"),
    ("Twitch", "twitch.tv", "Media"),
    ("Steam", "steampowered.com", "Gaming"),
    ("Steam Community", "steamcommunity.com", "Gaming"),
    ("Epic Games", "epicgames.com", "Gaming"),
    ("CloudFront", "cloudfront.net", "CDN"),
    ("AWS", "aws.amazon.com", "Cloud"),
    ("Google Cloud", "cloud.google.com", "Cloud"),
    ("Docker", "docker.com", "Developer"),
    ("Docker Hub", "hub.docker.com", "Developer"),
    ("npm", "npmjs.com", "Developer"),
    ("PyPI", "pypi.org", "Developer"),
    ("Stack Overflow", "stackoverflow.com", "Developer"),
    ("Mozilla", "mozilla.org", "Reference"),
    ("Rust", "rust-lang.org", "Developer"),

    ("Mozilla MDN", "developer.mozilla.org", "Developer"),
    ("npm Registry", "registry.npmjs.org", "Developer"),
    ("Microsoft Docs", "learn.microsoft.com", "Developer"),
    ("Stack Exchange", "stackexchange.com", "Developer"),
    ("Python", "python.org", "Developer"),
    ("Python Docs", "docs.python.org", "Developer"),
    ("Rust Docs", "doc.rust-lang.org", "Developer"),
    ("Ubuntu", "ubuntu.com", "Developer"),
    ("Debian", "debian.org", "Developer"),
    ("Cloudflare Radar", "radar.cloudflare.com", "Cloud"),
    ("Cloudflare Workers", "workers.dev", "Cloud"),
    ("Vercel", "vercel.com", "Cloud"),
    ("Netlify", "netlify.com", "Cloud"),
    ("DigitalOcean", "digitalocean.com", "Cloud"),
    ("Heroku", "heroku.com", "Cloud"),
    ("Oracle Cloud", "oracle.com", "Cloud"),
    ("IBM", "ibm.com", "Cloud"),
    ("Alibaba", "alibabacloud.com", "Cloud"),
    ("Tencent Cloud", "cloud.tencent.com", "Cloud"),
    ("Cloudflare Pages", "pages.dev", "Cloud"),
    ("Reddit Media", "redd.it", "Media"),
    ("Pinterest", "pinterest.com", "Social"),
    ("Snapchat", "snapchat.com", "Social"),
    ("Discord CDN", "discordapp.com", "Social"),
    ("Mastodon", "mastodon.social", "Social"),
    ("Quora", "quora.com", "Social"),
    ("Medium", "medium.com", "Media"),
    ("IMDb", "imdb.com", "Media"),
    ("Rotten Tomatoes", "rottentomatoes.com", "Media"),
    ("Fandom", "fandom.com", "Reference"),
    ("Britannica", "britannica.com", "Reference"),
    ("Khan Academy", "khanacademy.org", "Education"),
    ("Coursera", "coursera.org", "Education"),
    ("Udemy", "udemy.com", "Education"),
    ("Zoom", "zoom.us", "Business"),]


MAX_SCAN_TARGETS = 100
SCAN_CONCURRENCY = 8
SESSION_RETENTION = 3
TARGET_BENCHMARK_COUNT = 3000
TARGET_CUSTOM_LIMIT = 20
TARGET_BENCHMARK_SECONDS = 30.0
TARGET_PROBE_CONCURRENCY = 32
LOG_MAX_BYTES = 15 * 1024 * 1024
TRANCO_TARGET_URL = "https://tranco-list.eu/top-1m.csv.zip"
TARGET_CATALOG_PATH = DATA_DIR / "target_catalog.txt"
