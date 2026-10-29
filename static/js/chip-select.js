/**
 * Componente de filtro tipo "chips" — imita el look de selects con
 * placeholder ("Select Brands...") y las opciones elegidas mostradas como
 * etiquetas removibles, en vez de un <select multiple> nativo.
 *
 * Uso:
 *   const cs = createChipSelect(document.getElementById('f-retail'), {
 *     placeholder: 'Select Retail...'
 *   });
 *   await populateChipSelect(cs, '/api/retails/');
 *   cs.getValues() -> ["1", "3"]
 *   cs.onChange(() => { ... })
 */

function createChipSelect(container, { placeholder = "Select..." } = {}) {
  container.classList.add("chip-select");
  container.innerHTML = `
    <div class="cs-box" tabindex="0">
      <div class="cs-chips"></div>
      <input class="cs-input" type="text" placeholder="${placeholder}" autocomplete="off">
    </div>
    <div class="cs-dropdown" hidden></div>
  `;

  const box = container.querySelector(".cs-box");
  const chipsEl = container.querySelector(".cs-chips");
  const input = container.querySelector(".cs-input");
  const dropdown = container.querySelector(".cs-dropdown");

  let options = []; // [{value, label}]
  let selected = new Set();
  let changeCallback = null;

  function renderChips() {
    chipsEl.innerHTML = "";
    const selectedItems = options.filter(o => selected.has(String(o.value)));
    selectedItems.slice(0, 3).forEach(o => {
      const chip = document.createElement("span");
      chip.className = "cs-chip";
      chip.innerHTML = `${escapeHtml(o.label)} <button type="button" data-value="${o.value}">&times;</button>`;
      chipsEl.appendChild(chip);
    });
    if (selectedItems.length > 3) {
      const more = document.createElement("span");
      more.className = "cs-chip cs-chip-more";
      more.textContent = `+ ${selectedItems.length - 3}`;
      chipsEl.appendChild(more);
    }
    input.placeholder = selectedItems.length ? "" : placeholder;
  }

  function renderDropdown(filterText = "") {
    const q = filterText.trim().toLowerCase();
    const visible = options.filter(o =>
      !selected.has(String(o.value)) && o.label.toLowerCase().includes(q)
    );
    if (!visible.length) {
      dropdown.innerHTML = `<div class="cs-empty">Sin resultados</div>`;
    } else {
      dropdown.innerHTML = visible
        .slice(0, 100)
        .map(o => `<div class="cs-option" data-value="${o.value}">${escapeHtml(o.label)}</div>`)
        .join("");
    }
    dropdown.hidden = false;
  }

  function closeDropdown() {
    dropdown.hidden = true;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
  }

  box.addEventListener("click", () => {
    input.focus();
    renderDropdown(input.value);
  });

  input.addEventListener("input", () => renderDropdown(input.value));
  input.addEventListener("focus", () => renderDropdown(input.value));

  dropdown.addEventListener("click", (e) => {
    const opt = e.target.closest(".cs-option");
    if (!opt) return;
    selected.add(opt.dataset.value);
    input.value = "";
    renderChips();
    renderDropdown("");
    if (changeCallback) changeCallback();
  });

  chipsEl.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-value]");
    if (!btn) return;
    e.stopPropagation();
    selected.delete(btn.dataset.value);
    renderChips();
    if (changeCallback) changeCallback();
  });

  document.addEventListener("click", (e) => {
    if (!container.contains(e.target)) closeDropdown();
  });

  return {
    setOptions(items) {
      options = items.map(i => ({ value: String(i.value), label: i.label }));
      // conserva selección previa que siga siendo válida
      selected = new Set([...selected].filter(v => options.some(o => o.value === v)));
      renderChips();
    },
    getValues() {
      return Array.from(selected);
    },
    clear() {
      selected = new Set();
      renderChips();
    },
    onChange(cb) {
      changeCallback = cb;
    },
  };
}

async function populateChipSelect(chipSelect, url, { valueKey = "id", labelKey = "code" } = {}) {
  const items = await fetchJSON(url);
  chipSelect.setOptions(items.map(i => ({ value: i[valueKey], label: i[labelKey] })));
  return items;
}
