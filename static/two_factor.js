const tfMessage = document.querySelector("#twoFactorMessage");
const tfSetupBox = document.querySelector("#twoFactorSetup");

async function tfPost(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({csrf: ID.csrf, ...payload}),
  });
  const data = await response.json().catch(() => ({}));
  return {response, data};
}

document.querySelector("#setup2fa")?.addEventListener("click", async () => {
  tfMessage.textContent = "";
  const password = document.querySelector("#setup2faPassword").value;
  try {
    const {response, data} = await tfPost(`${ID.base}/api/account/2fa/setup`, {current: password});
    if (!response.ok) { tfMessage.textContent = data.error || "Unable to start 2FA setup."; return; }
    document.querySelector("#twoFactorSecret").textContent = data.secret;
    const qr = document.querySelector("#twoFactorQr");
    if (qr) { qr.src = `${ID.base}/api/account/2fa/qr?t=${Date.now()}`; qr.hidden = false; }
    tfSetupBox?.classList.remove("hidden");
    tfMessage.textContent = "Setup created. Add the secret to your authenticator, then enter its current code.";
  } catch { tfMessage.textContent = "Unable to start 2FA setup."; }
});

document.querySelector("#confirm2fa")?.addEventListener("click", async () => {
  const code = document.querySelector("#setup2faCode").value.trim();
  try {
    const {response, data} = await tfPost(`${ID.base}/api/account/2fa/confirm`, {code});
    if (!response.ok) { tfMessage.textContent = data.error || "Unable to enable 2FA."; return; }
    window.location.reload();
  } catch { tfMessage.textContent = "Unable to enable 2FA."; }
});

document.querySelector("#disable2fa")?.addEventListener("click", async () => {
  try {
    const {response, data} = await tfPost(`${ID.base}/api/account/2fa/disable`, {
      current: document.querySelector("#disable2faPassword").value,
      code: document.querySelector("#disable2faCode").value.trim(),
    });
    if (!response.ok) { tfMessage.textContent = data.error || "Unable to disable 2FA."; return; }
    window.location.reload();
  } catch { tfMessage.textContent = "Unable to disable 2FA."; }
});

document.querySelector("#copy2faSecret")?.addEventListener("click", async () => {
  const value = document.querySelector("#twoFactorSecret")?.textContent || "";
  try { await navigator.clipboard.writeText(value); tfMessage.textContent = "Secret copied."; }
  catch { tfMessage.textContent = "Copy failed. Copy the secret manually."; }
});
