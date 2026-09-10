const message = document.querySelector("#accountMessage");

async function postJson(url, payload) {
    const response = await fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
    });

    const data = await response.json();
    return { response, data };
}

document.querySelector("#saveUsername")?.addEventListener("click", async () => {
    const username = document.querySelector("#username").value.trim();

    try {
        const { response, data } = await postJson(
            `${ID.base}/api/account/username`,
            {
                csrf: ID.csrf,
                username,
            },
        );

        message.textContent = response.ok
            ? "Username saved."
            : data.error || "Unable to save username.";
    } catch {
        message.textContent = "Unable to save username.";
    }
});

document.querySelector("#changePassword")?.addEventListener("click", async () => {
    try {
        const { response, data } = await postJson(
            `${ID.base}/api/account/password`,
            {
                csrf: ID.csrf,
                current: document.querySelector("#currentPassword").value,
                new: document.querySelector("#newPassword").value,
                confirm: document.querySelector("#confirmPassword").value,
            },
        );

        if (!response.ok) {
            message.textContent = data.error || "Unable to change password.";
            return;
        }

        message.textContent = "Password changed. Redirecting to login…";
        window.setTimeout(() => {
            window.location.href = data.redirect;
        }, 900);
    } catch {
        message.textContent = "Unable to change password.";
    }
});
