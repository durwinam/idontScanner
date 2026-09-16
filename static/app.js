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


(function bootLoader(){
    const loader=document.getElementById("appBootLoader");
    if(!loader) return;
    const startedAt=performance.now();
    const minVisible=window.matchMedia("(max-width: 760px)").matches ? 1500 : 900;
    let hidden=false;
    const hide=()=>{
      if(hidden) return;
      const wait=Math.max(0,minVisible-(performance.now()-startedAt));
      setTimeout(()=>{
        if(hidden) return;
        hidden=true;
        loader.classList.add("is-ready");
        setTimeout(()=>loader.remove(),520);
      },wait);
    };
    const ready=()=>requestAnimationFrame(()=>requestAnimationFrame(hide));
    if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",ready,{once:true});
    else ready();
})();


/* v4.0.0 UI control layer: replace browser-native select chrome everywhere. */
(function customSelects() {
    const roots = new Set();
    const closeAll = (except = null) => {
        document.querySelectorAll('.idont-select.open').forEach((root) => {
            if (root !== except) root.classList.remove('open');
        });
    };

    const sync = (select, root, menu, triggerLabel) => {
        const option = select.options[select.selectedIndex];
        if (option) triggerLabel.textContent = option.textContent.trim();
        menu.querySelectorAll('[data-select-value]').forEach((item) => {
            item.classList.toggle('selected', item.dataset.selectValue === select.value);
        });
    };

    const enhance = (select) => {
        if (!select || select.dataset.idontEnhanced === '1' || select.multiple) return;
        select.dataset.idontEnhanced = '1';
        const wrapper = document.createElement('div');
        wrapper.className = 'idont-select';
        wrapper.dataset.for = select.id || '';
        select.parentNode.insertBefore(wrapper, select);
        wrapper.appendChild(select);

        const trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.className = 'idont-select-trigger';
        trigger.setAttribute('aria-haspopup', 'listbox');
        trigger.setAttribute('aria-expanded', 'false');
        const label = document.createElement('span');
        const chevron = document.createElement('span');
        chevron.className = 'idont-select-chevron';
        chevron.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 9 5 5 5-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
        trigger.append(label, chevron);

        const menu = document.createElement('div');
        menu.className = 'idont-select-menu';
        menu.setAttribute('role', 'listbox');
        Array.from(select.options).forEach((option) => {
            const item = document.createElement('button');
            item.type = 'button';
            item.dataset.selectValue = option.value;
            item.setAttribute('role', 'option');
            item.textContent = option.textContent.trim();
            item.addEventListener('click', (event) => {
                event.preventDefault();
                event.stopPropagation();
                select.value = option.value;
                select.dispatchEvent(new Event('change', { bubbles: true }));
                sync(select, wrapper, menu, label);
                closeAll();
            });
            menu.appendChild(item);
        });
        wrapper.append(trigger, menu);
        roots.add(wrapper);
        sync(select, wrapper, menu, label);

        const reposition = () => {
            if (!wrapper.classList.contains('open')) return;
            const rect = trigger.getBoundingClientRect();
            const maxHeight = Math.min(320, window.innerHeight - 24);
            menu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - rect.width - 8))}px`;
            menu.style.width = `${rect.width}px`;
            menu.style.maxHeight = `${maxHeight}px`;
            const below = window.innerHeight - rect.bottom;
            const above = rect.top;
            menu.style.top = below >= Math.min(320, menu.scrollHeight + 8) || below >= above
                ? `${Math.min(window.innerHeight - 8, rect.bottom + 7)}px`
                : `${Math.max(8, rect.top - Math.min(320, menu.scrollHeight) - 7)}px`;
        };
        trigger.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            const willOpen = !wrapper.classList.contains('open');
            closeAll(wrapper);
            wrapper.classList.toggle('open', willOpen);
            trigger.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
            if (willOpen) reposition();
        });
        select.addEventListener('change', () => sync(select, wrapper, menu, label));
        window.addEventListener('resize', reposition, { passive: true });
        window.addEventListener('scroll', reposition, { passive: true });
    };

    document.querySelectorAll('select').forEach(enhance);
    document.addEventListener('pointerdown', (event) => {
        if (!event.target.closest('.idont-select')) closeAll();
    }, true);
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') closeAll();
    });
})();
