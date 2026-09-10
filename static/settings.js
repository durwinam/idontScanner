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

        document.querySelector("#telegramOwnerId").value = data.owner_id || "";
        document.querySelector("#telegramAdminIds").value = (data.admin_ids || []).join(", ");
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
