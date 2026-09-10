const ID = window.IDONT || {};

const $ = (selector, root = document) => root.querySelector(selector);

const sidebar = $("#sidebar");
const overlay = $("#overlay");

function closeMenu() {
    sidebar?.classList.remove("open");
    overlay?.classList.remove("show");
}

function openMenu() {
    sidebar?.classList.add("open");
    overlay?.classList.add("show");
}

$("#menuOpen")?.addEventListener("click", openMenu);
$("#menuClose")?.addEventListener("click", closeMenu);
overlay?.addEventListener("click", closeMenu);
