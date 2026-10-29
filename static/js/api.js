/**
 * Helpers compartidos para llamar a los endpoints /api/* y poblar los
 * <select multiple> de filtros. La forma de los query params replica la
 * que mapeamos en 3Eye: categoryIds[]=X&categoryIds[]=Y, etc.
 */

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Error ${res.status} en ${url}`);
  return res.json();
}

/**
 * Fecha en formato YYYY-MM-DD usando la ZONA HORARIA LOCAL del navegador,
 * no UTC. Usar date.toISOString() aquí es un bug clásico: convierte a UTC,
 * así que en Perú (UTC-5) después de las 7pm ya devuelve la fecha de
 * MAÑANA, y el backend (que calcula "hoy" con la fecha local del server)
 * nunca encuentra coincidencias. Todas las fechas que arma el frontend
 * para mandar al backend deben pasar por aquí.
 */
function localDateISO(date = new Date()) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function selectedValues(selectEl) {
  return Array.from(selectEl.selectedOptions).map(o => o.value);
}

function appendListParam(params, name, values) {
  values.forEach(v => params.append(`${name}[]`, v));
}

async function populateSelect(selectEl, url, { valueKey = "id", labelKey = "code" } = {}) {
  const items = await fetchJSON(url);
  selectEl.innerHTML = "";
  items.forEach(item => {
    const opt = document.createElement("option");
    opt.value = item[valueKey];
    opt.textContent = item[labelKey];
    selectEl.appendChild(opt);
  });
  return items;
}

function renderEmpty(container, message = "No data") {
  container.innerHTML = `<p class="empty">${message}</p>`;
}

function renderTable(container, columns, rows) {
  if (!rows.length) {
    renderEmpty(container);
    return;
  }
  const thead = `<tr>${columns.map(c => `<th>${c.label}</th>`).join("")}</tr>`;
  const tbody = rows.map(row => {
    const cells = columns.map(c => `<td>${c.render ? c.render(row) : (row[c.key] ?? "")}</td>`).join("");
    return `<tr>${cells}</tr>`;
  }).join("");
  container.innerHTML = `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
}

function renderPagination(container, meta, onPageChange) {
  if (!meta || meta.totalPages <= 1) {
    container.innerHTML = "";
    return;
  }
  const total = meta.totalPages;
  const current = meta.page;
  // Hasta 7 paginas se muestran todas. Con mas: primera, ultima y las cercanas a la actual;
  // el resto se resume con "…" (un hueco de una sola pagina se llena con su numero).
  const shown = total <= 7
    ? Array.from({ length: total }, (_, i) => i + 1)
    : [...new Set([1, total, current - 2, current - 1, current, current + 1, current + 2])]
        .filter(p => p >= 1 && p <= total)
        .sort((a, b) => a - b);
  const items = [`<button data-page="${current - 1}" ${current === 1 ? "disabled" : ""}>‹</button>`];
  let previous = 0;
  shown.forEach(p => {
    if (p - previous === 2) {
      items.push(`<button data-page="${p - 1}">${p - 1}</button>`);
    } else if (p - previous > 2) {
      items.push('<span class="page-gap">…</span>');
    }
    items.push(`<button data-page="${p}" class="${p === current ? "active" : ""}">${p}</button>`);
    previous = p;
  });
  items.push(`<button data-page="${current + 1}" ${current === total ? "disabled" : ""}>›</button>`);
  container.innerHTML = items.join("");
  container.querySelectorAll("button:not([disabled])").forEach(btn => {
    btn.addEventListener("click", () => onPageChange(Number(btn.dataset.page)));
  });
}
