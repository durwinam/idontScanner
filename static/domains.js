const searchInput = document.querySelector("#domainSearch");

searchInput?.addEventListener("input", (event) => {
    const query = event.target.value.toLowerCase();

    document.querySelectorAll(".domain-row").forEach((row) => {
        const haystack = row.dataset.search?.toLowerCase() || "";
        row.style.display = haystack.includes(query) ? "" : "none";
    });
});

document.querySelectorAll("[data-toggle]").forEach((input) => {
    input.addEventListener("change", async (event) => {
        try {
            await fetch(
                `${ID.base}/api/domains/${event.target.dataset.toggle}/toggle`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({ csrf: ID.csrf }),
                },
            );
        } catch {
            event.target.checked = !event.target.checked;
        }
    });
});

document.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
        if (!window.confirm("Delete this custom domain?")) {
            return;
        }

        try {
            const response = await fetch(
                `${ID.base}/api/domains/${button.dataset.delete}`,
                {
                    method: "DELETE",
                    headers: {
                        "x-csrf-token": ID.csrf,
                    },
                },
            );

            if (response.ok) {
                window.location.reload();
                return;
            }

            const data = await response.json();
            window.alert(data.error || "Unable to delete domain.");
        } catch {
            window.alert("Unable to delete domain.");
        }
    });
});

const dialog = document.querySelector("#addDomainDialog");

document.querySelector("#addDomain")?.addEventListener("click", () => {
    dialog?.showModal();
});

document.querySelector("#addClose")?.addEventListener("click", () => {
    dialog?.close();
});

document.querySelector("#saveDomain")?.addEventListener("click", async (event) => {
    event.preventDefault();

    const body = {
        csrf: ID.csrf,
        label: document.querySelector("#newLabel").value,
        domain: document.querySelector("#newDomain").value,
        category: document.querySelector("#newCategory").value,
    };

    try {
        const response = await fetch(`${ID.base}/api/domains`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(body),
        });

        if (response.ok) {
            window.location.reload();
            return;
        }

        const data = await response.json();
        window.alert(data.error || "Unable to add domain.");
    } catch {
        window.alert("Unable to add domain.");
    }
});
