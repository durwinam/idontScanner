const updateNotice = document.querySelector("#updateNotice");
const updateNoticeTitle = document.querySelector("#updateNoticeTitle");
const updateNoticeText = document.querySelector("#updateNoticeText");
const updateNoticeClose = document.querySelector("#updateNoticeClose");

function versionParts(value) {
    const match = String(value || "").trim().match(/^v?(\d+)\.(\d+)\.(\d+)$/);
    return match ? match.slice(1).map(Number) : null;
}

function isNewer(remote, local) {
    const remoteParts = versionParts(remote);
    const localParts = versionParts(local);
    if (!remoteParts || !localParts) return false;
    for (let index = 0; index < 3; index += 1) {
        if (remoteParts[index] !== localParts[index]) {
            return remoteParts[index] > localParts[index];
        }
    }
    return false;
}

async function checkForUpdate() {
    try {
        const response = await fetch(`${ID.base}/api/update-check`, {cache: "no-store"});
        if (!response.ok) return;
        const data = await response.json();
        if (!data.update_available) return;

        updateNoticeTitle.textContent = `New update available · ${data.latest_version}`;
        updateNoticeText.textContent = `Installed ${data.current_version}. Run sudo idontScanner update in the terminal.`;
        updateNotice.classList.remove("hidden");
    } catch {
        // Update checks are intentionally non-blocking.
    }
}

updateNoticeClose?.addEventListener("click", () => {
    updateNotice.classList.add("hidden");
});

checkForUpdate();
