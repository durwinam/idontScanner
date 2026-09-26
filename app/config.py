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
    else "v4.5.0"
)
UPDATE_VERSION_URL = "https://raw.githubusercontent.com/durwinam/idontScanner/main/VERSION"

DEFAULT_DOMAINS = [('Cloudflare', 'cloudflare.com', 'CDN'), ('Cloudflare Docs', 'developers.cloudflare.com', 'Developer'), ('Cloudflare API', 'api.cloudflare.com', 'Cloud'), ('Cloudflare Radar', 'radar.cloudflare.com', 'Cloud'), ('Fastly', 'fastly.com', 'CDN'), ('Fastly Developer', 'developer.fastly.com', 'Developer'), ('Akamai', 'akamai.com', 'CDN'), ('Akamai Developer', 'developer.akamai.com', 'Developer'), ('Bunny', 'bunny.net', 'CDN'), ('jsDelivr', 'cdn.jsdelivr.net', 'CDN'), ('cdnjs', 'cdnjs.cloudflare.com', 'CDN'), ('unpkg', 'unpkg.com', 'Developer'), ('GitHub', 'github.com', 'Developer'), ('GitHub API', 'api.github.com', 'Developer'), ('GitHub Raw', 'raw.githubusercontent.com', 'Developer'), ('GitHub Pages', 'github.io', 'Developer'), ('GitLab', 'gitlab.com', 'Developer'), ('GitLab Pages', 'gitlab.io', 'Developer'), ('Bitbucket', 'bitbucket.org', 'Developer'), ('npm', 'npmjs.com', 'Developer'), ('npm Registry', 'registry.npmjs.org', 'Developer'), ('PyPI', 'pypi.org', 'Developer'), ('Python', 'python.org', 'Developer'), ('Python Docs', 'docs.python.org', 'Developer'), ('Rust', 'rust-lang.org', 'Developer'), ('Rust Docs', 'doc.rust-lang.org', 'Developer'), ('Mozilla', 'mozilla.org', 'Reference'), ('MDN', 'developer.mozilla.org', 'Developer'), ('Mozilla Services', 'services.mozilla.com', 'Reference'), ('Ubuntu', 'ubuntu.com', 'Developer'), ('Ubuntu Packages', 'packages.ubuntu.com', 'Developer'), ('Debian', 'debian.org', 'Developer'), ('Debian Packages', 'packages.debian.org', 'Developer'), ('Arch Linux', 'archlinux.org', 'Developer'), ('Alpine Linux', 'alpinelinux.org', 'Developer'), ('Fedora', 'fedoraproject.org', 'Developer'), ('Kubernetes', 'kubernetes.io', 'Developer'), ('Docker', 'docker.com', 'Developer'), ('Docker Hub', 'hub.docker.com', 'Developer'), ('Homebrew', 'brew.sh', 'Developer'), ('Go', 'go.dev', 'Developer'), ('Deno', 'deno.com', 'Developer'), ('Bun', 'bun.sh', 'Developer'), ('Node.js', 'nodejs.org', 'Developer'), ('npm Docs', 'docs.npmjs.com', 'Developer'), ('Stack Overflow', 'stackoverflow.com', 'Developer'), ('Stack Exchange', 'stackexchange.com', 'Developer'), ('JetBrains', 'jetbrains.com', 'Developer'), ('IntelliJ', 'www.jetbrains.com', 'Developer'), ('Vercel', 'vercel.com', 'Cloud'), ('Vercel App', 'vercel.app', 'Cloud'), ('Netlify', 'netlify.com', 'Cloud'), ('Netlify App', 'netlify.app', 'Cloud'), ('DigitalOcean', 'digitalocean.com', 'Cloud'), ('Heroku', 'heroku.com', 'Cloud'), ('Oracle Cloud', 'oracle.com', 'Cloud'), ('IBM', 'ibm.com', 'Cloud'), ('Alibaba Cloud', 'alibabacloud.com', 'Cloud'), ('Tencent Cloud', 'cloud.tencent.com', 'Cloud'), ('AWS', 'aws.amazon.com', 'Cloud'), ('AWS Docs', 'docs.aws.amazon.com', 'Developer'), ('AWS Status', 'health.aws.amazon.com', 'Cloud'), ('Amazon S3', 's3.amazonaws.com', 'Cloud'), ('CloudFront', 'cloudfront.net', 'CDN'), ('Google', 'google.com', 'Search'), ('Google APIs', 'googleapis.com', 'Cloud'), ('Gstatic', 'gstatic.com', 'Cloud'), ('Google Cloud', 'cloud.google.com', 'Cloud'), ('Google Developers', 'developers.google.com', 'Developer'), ('Google Fonts', 'fonts.googleapis.com', 'Developer'), ('Google Storage', 'storage.googleapis.com', 'Cloud'), ('Google Accounts', 'accounts.google.com', 'Search'), ('Google Drive', 'drive.google.com', 'Cloud'), ('Google Docs', 'docs.google.com', 'Cloud'), ('Google Translate', 'translate.google.com', 'Search'), ('Google Maps', 'maps.google.com', 'Maps'), ('Microsoft', 'microsoft.com', 'Microsoft'), ('Microsoft Learn', 'learn.microsoft.com', 'Developer'), ('Microsoft 365', 'microsoft365.com', 'Business'), ('Bing', 'bing.com', 'Search'), ('MSN', 'msn.com', 'Search'), ('Azure', 'azure.com', 'Cloud'), ('Azure Edge', 'azureedge.net', 'CDN'), ('Microsoft Login', 'login.microsoftonline.com', 'Business'), ('Apple', 'apple.com', 'Apple'), ('Apple Developer', 'developer.apple.com', 'Developer'), ('Apple Support', 'support.apple.com', 'Apple'), ('iCloud', 'icloud.com', 'Apple'), ('App Store', 'apps.apple.com', 'Apple'), ('Apple Music', 'music.apple.com', 'Media'), ('Wikipedia', 'wikipedia.org', 'Reference'), ('Wikimedia', 'wikimedia.org', 'Reference'), ('Internet Archive', 'archive.org', 'Reference'), ('Britannica', 'britannica.com', 'Reference'), ('Khan Academy', 'khanacademy.org', 'Education'), ('Coursera', 'coursera.org', 'Education'), ('edX', 'edx.org', 'Education'), ('Udemy', 'udemy.com', 'Education'), ('Medium', 'medium.com', 'Media'), ('Substack', 'substack.com', 'Media'), ('WordPress', 'wordpress.org', 'Developer'), ('WordPress.com', 'wordpress.com', 'Cloud'), ('Ghost', 'ghost.org', 'Developer'), ('Notion', 'notion.so', 'Business'), ('Figma', 'figma.com', 'Business'), ('Canva', 'canva.com', 'Business'), ('Slack', 'slack.com', 'Business'), ('Zoom', 'zoom.us', 'Business'), ('Dropbox', 'dropbox.com', 'Cloud'), ('Box', 'box.com', 'Cloud'), ('Atlassian', 'atlassian.com', 'Business'), ('Trello', 'trello.com', 'Business'), ('Discord', 'discord.com', 'Social'), ('Telegram', 'telegram.org', 'Social'), ('WhatsApp', 'whatsapp.com', 'Social'), ('Reddit', 'reddit.com', 'Social'), ('Pinterest', 'pinterest.com', 'Social'), ('Quora', 'quora.com', 'Social'), ('Mastodon', 'mastodon.social', 'Social'), ('Instagram', 'instagram.com', 'Social'), ('Facebook', 'facebook.com', 'Social'), ('X', 'x.com', 'Social'), ('YouTube', 'youtube.com', 'Media'), ('Spotify', 'spotify.com', 'Media'), ('Netflix', 'netflix.com', 'Media'), ('Twitch', 'twitch.tv', 'Media'), ('Steam', 'steampowered.com', 'Gaming'), ('Steam Community', 'steamcommunity.com', 'Gaming'), ('Epic Games', 'epicgames.com', 'Gaming'), ('OpenAI', 'openai.com', 'AI'), ('ChatGPT', 'chatgpt.com', 'AI'), ('Anthropic', 'anthropic.com', 'AI'), ('Claude', 'claude.ai', 'AI'), ('Hugging Face', 'huggingface.co', 'AI'), ('Kaggle', 'kaggle.com', 'AI'), ('ArXiv', 'arxiv.org', 'Research'), ('ORCID', 'orcid.org', 'Research'), ('DOI', 'doi.org', 'Research'), ('Semantic Scholar', 'semanticscholar.org', 'Research'), ('Aparat', 'aparat.com', 'Iran'), ('Digikala', 'digikala.com', 'Iran'), ('Divar', 'divar.ir', 'Iran'), ('Snapp', 'snapp.ir', 'Iran'), ('ArvanCloud', 'arvancloud.ir', 'Iran'), ('MCI', 'mci.ir', 'Iran'), ('Irancell', 'irancell.ir', 'Iran'), ('GitHub Education', 'education.github.com', 'Education'), ('FreeCodeCamp', 'freecodecamp.org', 'Education'), ('Web.dev', 'web.dev', 'Developer'), ('OWASP', 'owasp.org', 'Security')]


MAX_SCAN_TARGETS = 150
SCAN_CONCURRENCY = 8
SESSION_RETENTION = 3
TARGET_BENCHMARK_COUNT = 3000
TARGET_CUSTOM_LIMIT = 20
TARGET_BENCHMARK_SECONDS = 30.0
TARGET_PROBE_CONCURRENCY = 32
LOG_MAX_BYTES = 15 * 1024 * 1024
TRANCO_TARGET_URL = "https://tranco-list.eu/top-1m.csv.zip"
TARGET_CATALOG_PATH = DATA_DIR / "target_catalog.txt"
