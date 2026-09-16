const schedulerMessage = document.querySelector("#schedulerMessage");
const telegramMessage = document.querySelector("#telegramMessage");
const currentScheduler = Number(
    document.querySelector("#schedulerIntervalValue")?.textContent || 60,
);

const schedulerEnabled = document.querySelector("#schedulerEnabled");
const interval = document.querySelector("#interval");
const notifyMode = document.querySelector("#notifyMode");
const schedulerBadge = document.querySelector("#schedulerBadge");

if (interval) {
    interval.value = String(currentScheduler);
}

const showMessage = (element, text, type = "") => {
    if (!element) {
        return;
    }

    element.textContent = text;
    element.classList.toggle("error", type === "error");
};

document.querySelector("#saveScheduler")?.addEventListener("click", async () => {
    const body = {
        csrf: ID.csrf,
        enabled: Boolean(schedulerEnabled?.checked),
        interval_minutes: Number(interval?.value || 60),
        notify_mode: notifyMode?.value || "all",
    };

    showMessage(schedulerMessage, "Saving scheduler…");

    try {
        const response = await fetch(`${ID.base}/api/scheduler`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(body),
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Unable to save scheduler.");
        }

        showMessage(schedulerMessage, "Scheduler saved.");

        if (schedulerBadge) {
            schedulerBadge.textContent = body.enabled ? "ON" : "OFF";
            schedulerBadge.classList.toggle("good", body.enabled);
        }
    } catch (error) {
        showMessage(schedulerMessage, error.message, "error");
    }
});

function setTelegramStatus(text, connected = false) {
    const status = document.querySelector("#telegramStatus");

    if (!status) {
        return;
    }

    status.classList.toggle("connected", connected);
    status.querySelector("span:last-child").textContent = text;
}

function setTelegramLink(url) {
    const link = document.querySelector("#openTelegram");

    if (!link) {
        return;
    }

    if (url) {
        link.href = url;
        link.hidden = false;
        return;
    }

    link.hidden = true;
    link.removeAttribute("href");
}

async function loadTelegramStatus() {
    try {
        const response = await fetch(`${ID.base}/api/telegram/status`, {
            cache: "no-store",
        });
        const data = await response.json();

        if (!data.configured) {
            setTelegramStatus("Telegram is not configured.");
            return;
        }

        const botName = data.username ? `@${data.username}` : "Telegram bot";
        const accessState = data.authorized
            ? `Owner ${data.owner_id || "not set"} · ${data.admin_ids?.length || 0} admin(s)`
            : "owner/admin access is not configured";

        setTelegramStatus(`${botName} connected · ${accessState}`, true);

        const ownerInput = document.querySelector("#telegramOwnerId");
        const adminsInput = document.querySelector("#telegramAdminIds");
        if (ownerInput) ownerInput.value = data.owner_id || "";
        if (adminsInput) adminsInput.value = (data.admin_ids || []).join(", ");
        const publicUrl = document.querySelector("#publicPanelUrl");
        if (publicUrl) publicUrl.value = data.public_panel_url || "";
        setTelegramLink(data.url);
    } catch {
        setTelegramStatus("Unable to check Telegram connection.");
    }
}

document.querySelector("#saveTelegram")?.addEventListener("click", async () => {
    const tokenInput = document.querySelector("#telegramToken");
    const token = tokenInput?.value.trim() || "";

    if (!token) {
        showMessage(telegramMessage, "Enter the Telegram bot token first.", "error");
        tokenInput?.focus();
        return;
    }

    showMessage(telegramMessage, "Connecting Telegram bot…");

    try {
        const response = await fetch(`${ID.base}/api/telegram`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                csrf: ID.csrf,
                token,
                owner_id: document.querySelector("#telegramOwnerId").value.trim(),
                admin_ids: document.querySelector("#telegramAdminIds").value.trim(),
                public_panel_url: document.querySelector("#publicPanelUrl")?.value.trim() || "",
            }),
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Unable to connect Telegram.");
        }

        tokenInput.value = "";
        showMessage(
            telegramMessage,
            data.username
                ? `Connected to @${data.username}. Open the bot and send /start.`
                : "Telegram bot connected. Open the bot and send /start.",
        );
        setTelegramStatus(
            data.username
                ? `@${data.username} connected · ${data.authorized ? "access configured" : "send /start to authorize"}`
                : "Telegram bot connected · send /start to authorize",
            true,
        );
        setTelegramLink(data.url);
    } catch (error) {
        showMessage(telegramMessage, error.message, "error");
    }
});

document.querySelector("#disableTelegram")?.addEventListener("click", async () => {
    showMessage(telegramMessage, "Disconnecting Telegram…");

    try {
        const response = await fetch(`${ID.base}/api/telegram`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                csrf: ID.csrf,
                token: "",
            }),
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Unable to disable Telegram.");
        }

        showMessage(telegramMessage, "Telegram integration disabled.");
        setTelegramStatus("Telegram is not configured.");
        setTelegramLink("");
        document.querySelector("#telegramToken").value = "";
    } catch (error) {
        showMessage(telegramMessage, error.message, "error");
    }
});

loadTelegramStatus();


async function loadPreferences() {
    const chart = document.querySelector("#resourceChartStyle");
    const range = document.querySelector("#resourceRange");
    const animations = document.querySelector("#animationsEnabled");
    if (!chart && !range && !animations) return;
    try {
        const response = await fetch(`${ID.base}/api/preferences`, { cache: "no-store" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Unable to load preferences.");
        if (chart) chart.value = data.resource_chart_style;
        if (range) range.value = String(data.resource_range);
        if (animations) animations.checked = Boolean(data.animations);
        document.documentElement.dataset.theme = data.theme || "dark";
        localStorage.setItem("idont_theme", data.theme || "dark");
        document.querySelectorAll("[data-theme-choice]").forEach((button) => {
            button.classList.toggle("selected", button.dataset.themeChoice === data.theme);
        });
    } catch (error) {
        showMessage(document.querySelector("#preferencesMessage"), error.message, "error");
    }
}

async function savePreferences() {
    const chart = document.querySelector("#resourceChartStyle");
    const range = document.querySelector("#resourceRange");
    const animations = document.querySelector("#animationsEnabled");
    const theme = document.documentElement.dataset.theme || "dark";
    const body = {
        csrf: ID.csrf, theme,
        resource_chart_style: chart?.value || "hybrid",
        resource_range: Number(range?.value || 60),
        animations: Boolean(animations?.checked),
    };
    const message = document.querySelector("#preferencesMessage");
    showMessage(message, "Saving preferences…");
    try {
        const response = await fetch(`${ID.base}/api/preferences`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Unable to save preferences.");
        document.documentElement.dataset.animations = data.animations ? "1" : "0";
        localStorage.setItem("idont_theme", data.theme);
        localStorage.setItem("idont_resource_chart_style", data.resource_chart_style);
        localStorage.setItem("idont_resource_range", String(data.resource_range));
        window.dispatchEvent(new CustomEvent("idont-preferences-changed", { detail: data }));
        showMessage(message, "Preferences saved.");
    } catch (error) { showMessage(message, error.message, "error"); }
}

document.querySelectorAll("[data-theme-choice]").forEach((button) => {
    button.addEventListener("click", () => {
        const theme = button.dataset.themeChoice;
        document.documentElement.dataset.theme = theme;
        document.querySelectorAll("[data-theme-choice]").forEach((item) => item.classList.toggle("selected", item === button));
    });
});
document.querySelector("#savePreferences")?.addEventListener("click", savePreferences);
loadPreferences();


async function testTelegramConnection() {
    const button = document.querySelector("#testTelegram");
    if (!button) return;
    button.disabled = true;
    button.classList.add("is-loading");
    showMessage(telegramMessage, "Testing Telegram bot connection…");
    try {
        const response = await fetch(`${ID.base}/api/telegram/test`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ csrf: ID.csrf }),
            cache: "no-store",
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Telegram connection test failed.");
        const label = data.username ? `@${data.username}` : (data.name || "bot");
        setTelegramStatus(`${label} connected · Telegram API OK`, true);
        showMessage(telegramMessage, `Bot connection successful: ${label}.`);
        setTelegramLink(data.url || "");
    } catch (error) {
        setTelegramStatus("Telegram connection test failed.", false);
        showMessage(telegramMessage, error.message, "error");
    } finally {
        button.disabled = false;
        button.classList.remove("is-loading");
    }
}

document.querySelector("#testTelegram")?.addEventListener("click", testTelegramConnection);
