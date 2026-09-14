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


async function loadSessions() {
    const box=document.querySelector('#sessions'); if(!box)return;
    try { const r=await fetch(`${ID.base}/api/sessions`,{cache:'no-store'}); const data=await r.json(); if(!r.ok) throw new Error(data.error||'Unable to load sessions.');
      box.innerHTML=data.length?data.map(s=>`<div class="device-card" data-session-id="${s.id}"><div class="device-icon">◉</div><div><b>${escapeHtml(s.device)}</b><small>IP · ${escapeHtml(s.ip)}</small><small>${escapeHtml(s.last_seen)}</small></div><button type="button" class="secondary session-revoke" data-session-id="${s.id}">Revoke</button></div>`).join(''):'<div class="empty">No recent devices.</div>';
      box.querySelectorAll('.session-revoke').forEach(b=>b.addEventListener('click',async()=>{if(!confirm('Revoke this session?'))return;const rr=await fetch(`${ID.base}/api/sessions/${b.dataset.sessionId}`,{method:'DELETE',headers:{'x-csrf-token':ID.csrf}});if(rr.ok)loadSessions();}));
    } catch {}
}
function escapeHtml(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');}
loadSessions();
