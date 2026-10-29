(function () {
  const fCategory = document.getElementById("f-category");
  const fEvent = document.getElementById("f-event");
  const fDate = document.getElementById("f-date");
  const eventFilter = document.getElementById("event-filter");
  const dateFilter = document.getElementById("date-filter");
  const tableWrap = document.getElementById("table-wrap");
  const pager = document.getElementById("pager");
  const tabs = document.querySelectorAll(".tab");
  const btnGraph = document.getElementById("btn-graph");
  const graphsSection = document.getElementById("graphs-section");

  const csRetail = createChipSelect(document.getElementById("f-retail"), { placeholder: "Select Retail..." });
  const csBrand = createChipSelect(document.getElementById("f-brand"), { placeholder: "Select Brands..." });
  const csFeature = createChipSelect(document.getElementById("f-feature"), { placeholder: "Select Features..." });
  const csProduct = createChipSelect(document.getElementById("f-product"), { placeholder: "Select Item..." });

  let mode = "search";
  let lastRows = [];
  let page = 1;          // pagina actual de la tabla (se pagina en el navegador)
  let pageSize = 25;
  let selectedProducts = new Set();
  let retailColors = {};   // code -> color hex
  let chartTracking = null;
  let chartByRetail = null;
  let pieCharts = [];

  // ---------------------------------------------------------------------
  // Tooltip flotante de la celda de precio.
  // Copia el aspecto del tooltip de los graficos (Chart.js):
  // fondo #10182B, texto claro, padding 10, bordes redondeados 8.
  // El texto va en data-* (no en title) para que se pueda dar formato y
  // controlar el contenido; `title`_native se puede quitar.
  // ---------------------------------------------------------------------
  let tipEl = null;

  function tipHtml(el) {
    return `<div>Precio Lista: ${esc(el.dataset.tipLista || "—")}</div>`
      + `<div>Precio actual : ${esc(el.dataset.tipActual || "—")}</div>`;
  }

  function placeTip(x, y) {
    const r = tipEl.getBoundingClientRect();
    let left = x + 16;
    let top = y + 18;
    if (left + r.width > window.innerWidth - 10) left = x - r.width - 16;
    if (top + r.height > window.innerHeight - 10) top = y - r.height - 18;
    tipEl.style.left = Math.max(10, left + window.scrollX) + "px";
    tipEl.style.top = Math.max(10, top + window.scrollY) + "px";
  }

  function showTip(el, x, y) {
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.className = "price-tip";
      document.body.appendChild(tipEl);
    }
    tipEl.innerHTML = tipHtml(el);
    tipEl.style.display = "block";
    placeTip(x, y);
  }

  function hideTip() {
    if (tipEl) tipEl.style.display = "none";
  }

  // Delegacion sobre el contenedor: la tabla se vuelve a pintar en cada
  // render, asi que los listeners no pueden vivir en cada celda.
  function bindPriceTips() {
    tableWrap.addEventListener("mouseover", e => {
      const el = e.target.closest("[data-tip-actual]");
      if (el) showTip(el, e.clientX, e.clientY);
    });
    tableWrap.addEventListener("mousemove", e => {
      if (tipEl && tipEl.style.display === "block") placeTip(e.clientX, e.clientY);
    });
    tableWrap.addEventListener("mouseleave", hideTip);
    tableWrap.addEventListener("mouseout", e => {
      if (e.target.closest("[data-tip-actual]")) hideTip();
    });
    window.addEventListener("scroll", hideTip, { passive: true });
  }

  async function init() {
    const categories = await fetchJSON("/api/categories/");
    fCategory.innerHTML = categories.map(c => `<option value="${c.id}">${c.code}</option>`).join("");

    const retailItems = await populateChipSelect(csRetail, "/api/retails/");
    retailItems.forEach(r => { retailColors[r.code] = r.color || "#c7c9de"; });

    await populateChipSelect(csBrand, "/api/brands/");
    await populateChipSelect(csFeature, "/api/features/");
    await populateChipSelect(csProduct, "/api/products");
    await populateSelect(fEvent, "/api/mkt-event/");

    // Los filtros solo actualizan su propia selección — la búsqueda se
    // dispara únicamente con el botón "Search" (o al cambiar de pestaña
    // Search/Top Sales, que sí debe refrescar de inmediato).
    if (fDate) {
      fDate.value = localDateISO();
    }

    search();
  }

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      mode = tab.dataset.mode;
      eventFilter.style.display = mode === "top-sales" ? "flex" : "none";
      dateFilter.style.display = mode === "top-sales" ? "flex" : "none";
      resetGraphs();
      search();
    });
  });

  document.getElementById("btn-search").addEventListener("click", search);
  document.getElementById("btn-refresh").addEventListener("click", search);
  document.getElementById("btn-export").addEventListener("click", exportXlsx);
  btnGraph.addEventListener("click", generateGraphs);

  bindPriceTips();

  function resetGraphs() {
    selectedProducts = new Set();
    btnGraph.disabled = true;
    graphsSection.style.display = "none";
  }

  async function search() {
    const params = new URLSearchParams();
    if (fCategory.value) params.append("categoryIds[]", fCategory.value);
    appendListParam(params, "retailIds", csRetail.getValues());
    appendListParam(params, "brandIds", csBrand.getValues());
    appendListParam(params, "featureIds", csFeature.getValues());
    appendListParam(params, "products", csProduct.getValues());

    if (mode === "top-sales") {
      params.set("hasSalesRank", "true");
      if (fCategory.value) params.set("categoryId", fCategory.value);
      const date = (fDate && fDate.value) || localDateISO();
      params.set("fromDate", date);
      params.set("toDate", date);
    }
    // En modo Search ("Modes") no se manda fecha: el backend siempre
    // devuelve el precio más reciente disponible por tienda.

    const data = await fetchJSON(`/api/prices/matrix?${params.toString()}`);
    lastRows = data;
    page = 1;
    resetGraphs();
    renderCurrent();
  }

  // Dibuja solo la pagina actual de la tabla (Search o Top Sales) y su barra de paginas
  function renderCurrent() {
    if (mode === "top-sales") {
      if (!lastRows.length) {
        renderEmpty(tableWrap);
        renderPager(0);
        return;
      }
      renderTable(tableWrap, [
        { key: "product", label: "Product" },
        { key: "brand", label: "Brand" },
        { key: "retail", label: "Retail" },
        { key: "minPrice", label: "Price", render: r => {
            const chipAttrs = `class="price-chip" data-tip-actual="${esc("S/ " + r.minPrice.toFixed(2))}"`;
            return r.url
              ? `<a ${chipAttrs} href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">S/ ${r.minPrice.toFixed(2)}</a>`
              : `<span ${chipAttrs}>S/ ${r.minPrice.toFixed(2)}</span>`;
          } },
        { key: "salesRank", label: "Rank" },
      ], pageSlice(lastRows));
      renderPager(lastRows.length);
      return;
    }
    renderSearchTable(lastRows);
  }

  function pageSlice(rows) {
    const start = (page - 1) * pageSize;
    return rows.slice(start, start + pageSize);
  }

  function renderPager(total) {
    if (total <= 0) {
      pager.innerHTML = "";
      return;
    }
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (page > totalPages) page = totalPages;
    const from = (page - 1) * pageSize + 1;
    const to = Math.min(total, page * pageSize);
    pager.innerHTML = `
      <span class="pager-info">Mostrando ${from}–${to} de ${total}</span>
      <div class="pagination" id="pager-buttons"></div>
      <label class="pager-size">Por página
        <select id="page-size">
          ${[25, 50, 100].map(n => `<option value="${n}" ${n === pageSize ? "selected" : ""}>${n}</option>`).join("")}
        </select>
      </label>`;
    renderPagination(document.getElementById("pager-buttons"), { page, totalPages }, p => {
      page = p;
      renderCurrent();
      tableWrap.scrollIntoView({ block: "start" });
    });
    document.getElementById("page-size").addEventListener("change", e => {
      pageSize = Number(e.target.value);
      page = 1;
      renderCurrent();
    });
  }

  function esc(value) {
    return String(value).replace(/[&<>"']/g, c => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function retailBadge(code) {
    return `<span class="retail-badge"><img class="retail-logo" src="/static/img/logos/${esc(code)}.png" alt="${esc(code)}" title="${esc(code)}"></span>`;
  }

function positionBadge(position) {
    const map = {
      mas_barato: { label: "Más barato", cls: "badge-green" },
      mas_caro: { label: "Más caro", cls: "badge-gray" },
      igual_mercado: { label: "Precio de mercado", cls: "badge-gray" },
    };
    const info = map[position];
    if (!info) return "";
    return `<span class="ref-badge ${info.cls}" title="${info.label} vs. el resto del mercado">${info.label}</span>`;
  }

  // En table-layout:fixed los anchos fiables se declaran con <colgroup>. Las 4
  // fijas (checkbox, Categoria, Producto, Brand) conservan su ancho de
  // contenido; todas las columnas de tienda tienen el MISMO ancho minimo (el
  // de la tienda mas ancha), quedando compactas, iguales y centradas. Si
  // exceden el panel aparece el scroll horizontal.
  function fitFixedColumns(table) {
    if (!table) return;
    const headCells = Array.from(table.querySelectorAll("thead th"));
    if (headCells.length < 5) return;
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    if (!rows.length) return;
    const fixedCount = 4;
    const retailCount = headCells.length - fixedCount;

    // Mide el ancho natural de cada columna segun su CONTENIDO: en
    // table-layout:fixed las columnas ignoran el contenido.
    const prevLayout = table.style.tableLayout;
    table.style.tableLayout = "auto";
    table.style.width = "max-content";
    const colWidths = headCells.map((th, i) => {
      let w = th.getBoundingClientRect().width;
      rows.forEach(tr => {
        if (tr.cells[i]) {
          w = Math.max(w, tr.cells[i].getBoundingClientRect().width);
        }
      });
      return Math.ceil(w);
    });
    // Restaura fixed; la tabla usa el ancho de sus columnas.
    table.style.tableLayout = prevLayout || "fixed";
    table.style.width = "auto";

    const fixedWidths = colWidths.slice(0, fixedCount);
    const retailUniform = Math.max(...colWidths.slice(fixedCount));
    const widths = fixedWidths.concat(Array(retailCount).fill(retailUniform));

    // Elimina un colgroup previo (si quedo de otro render) y crea el nuevo.
    const old = table.querySelector("colgroup");
    if (old) old.remove();
    const colgroup = document.createElement("colgroup");
    colgroup.innerHTML = widths.map(w => `<col style="width:${w}px">`).join("");
    table.insertBefore(colgroup, table.firstChild);
  }

  function renderSearchTable(data) {
    if (!data.length) {
      renderEmpty(tableWrap);
      renderPager(0);
      return;
    }
    const retailCodes = new Set();
    data.forEach(row => Object.keys(row.prices).forEach(rc => retailCodes.add(rc)));
    const retailList = Array.from(retailCodes);

    const thead = `<tr>
      <th></th>
      <th>Category</th><th>Product</th><th>Brand</th>
      ${retailList.map(rc => `<th class="col-retail">${retailBadge(rc)}</th>`).join("")}
    </tr>`;

    const tbody = pageSlice(data).map(row => {
      const stock = row.stock || {};
      // El "mejor precio" (resaltado verde) solo considera tiendas con
      // stock — no tiene sentido destacar el precio de algo agotado.
      const inStockPrices = Object.entries(row.prices)
        .filter(([rc, p]) => p != null && stock[rc] !== false)
        .map(([, p]) => p);
      const minPrice = inStockPrices.length ? Math.min(...inStockPrices) : null;
      const checked = selectedProducts.has(row.product) ? "checked" : "";
      const priceCells = retailList.map(rc => {
        const p = row.prices[rc];
        if (p == null) return `<td class="col-retail">—</td>`;
        const priceDate = (row.priceDates && row.priceDates[rc]) || "";
        const badge = rc === row.refStore ? positionBadge(row.refPosition) : "";
        const seller = (row.sellers && row.sellers[rc]) || "";
        const listPrice = row.listPrices && row.listPrices[rc];
        const url = (row.urls && row.urls[rc]) || "";
        const listaTxt = listPrice ? `S/ ${Number(listPrice).toFixed(2)}` : "—";

        // El precio abre la pagina del producto en esa tienda: sirve para
        // comprobar contra la pagina que el dato scrapeado es correcto.
        const cls = stock[rc] === false ? "price-oos" : (p === minPrice ? "price-best" : "price-normal");
        const chipAttrs = `class="price-chip ${cls}" data-tip-lista="${esc(listaTxt)}"`
          + ` data-tip-actual="${esc("S/ " + p.toFixed(2))}"`;
        const label = url
          ? `<a ${chipAttrs} href="${esc(url)}" target="_blank" rel="noopener noreferrer">${p.toFixed(2)}</a>`
          : `<span ${chipAttrs}>${p.toFixed(2)}</span>`;
        const oos = stock[rc] === false ? `<span class="stock-badge">Sin stock</span>` : "";

        return `<td class="col-retail">${label}${oos}${badge}</td>`;
      }).join("");
      return `<tr>
        <td><input type="checkbox" class="row-check" data-product="${row.product}" ${checked}></td>
        <td>${row.category ?? ""}</td>
        <td>${row.product}${row.name ? `<span class="seller-note">${esc(row.name)}</span>` : ""}</td>
        <td>${row.brand ?? ""}</td>
        ${priceCells}
      </tr>`;
    }).join("");

    tableWrap.innerHTML = `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
    renderPager(data.length);

    // Las columnas fijas (checkbox, Categoria, Producto, Brand) conservan el
    // ancho exacto de su contenido y el espacio sobrante del panel va solo a
    // las columnas de tienda, que estan centradas. Sin esto el navegador
    // reparte el excedente entre TODAS las columnas y 'Producto' se estira.
    fitFixedColumns(tableWrap.querySelector("table"));

    tableWrap.querySelectorAll(".row-check").forEach(cb => {
      cb.addEventListener("change", () => {
        if (cb.checked) selectedProducts.add(cb.dataset.product);
        else selectedProducts.delete(cb.dataset.product);
        btnGraph.disabled = selectedProducts.size === 0;
      });
    });
  }

  function exportXlsx() {
    if (!lastRows.length) return;
    let rows;
    if (mode === "top-sales") {
      rows = lastRows.map(r => ({ Product: r.product, Brand: r.brand, Retail: r.retail, Price: r.minPrice, Rank: r.salesRank }));
    } else {
      rows = lastRows.map(r => {
        const base = { Category: r.category, Product: r.product, Brand: r.brand };
        Object.entries(r.prices).forEach(([rc, p]) => base[rc] = p);
        return base;
      });
    }
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Products");
    XLSX.writeFile(wb, "products_export.xlsx");
  }

  async function generateGraphs() {
    if (btnGraph.disabled) return;
    const products = Array.from(selectedProducts);
    if (!products.length) return;

    const fromInput = document.getElementById("graph-from");
    const toInput = document.getElementById("graph-to");
    const today = new Date();
    const twoWeeksAgo = new Date(today);
    twoWeeksAgo.setDate(today.getDate() - 14);
    if (!fromInput.value) fromInput.value = localDateISO(twoWeeksAgo);
    if (!toInput.value) toInput.value = localDateISO(today);

    document.getElementById("selected-chips").innerHTML = products
      .map(p => `<span class="cs-chip">${p}</span>`).join("");

    await loadGraphs(products, fromInput.value, toInput.value);

    fromInput.onchange = () => loadGraphs(products, fromInput.value, toInput.value);
    toInput.onchange = () => loadGraphs(products, fromInput.value, toInput.value);

    graphsSection.style.display = "block";
    graphsSection.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function loadGraphs(products, fromDate, toDate) {
    const params = new URLSearchParams();
    appendListParam(params, "products", products);
    params.set("fromDate", fromDate);
    params.set("toDate", toDate);
    const history = await fetchJSON(`/api/prices/history?${params.toString()}`);

    renderTrackingChart(history);
    renderPieCharts(history, products);
    renderByRetailChart(history, products);
  }

  function palette(i) {
    const colors = ["#7b6ef6", "#22c55e", "#f97316", "#0ea5e9", "#e11d48", "#a855f7", "#eab308"];
    return colors[i % colors.length];
  }

  function retailColorFor(code, fallbackIndex) {
    return retailColors[code] || palette(fallbackIndex);
  }

  function renderTrackingChart(history) {
    const series = {};
    history.forEach(row => {
      const key = `${row.product} · ${row.retail}`;
      series[key] = series[key] || { byDate: {}, retail: row.retail };
      series[key].byDate[row.date] = row.price;
    });
    const allDates = Array.from(new Set(history.map(r => r.date))).sort();

    const datasets = Object.entries(series).map(([label, info], i) => {
      const color = retailColorFor(info.retail, i);
      return {
        label,
        data: allDates.map(d => info.byDate[d] ?? null),
        borderColor: color,
        backgroundColor: color,
        tension: 0.25,
        spanGaps: true,
        pointRadius: 3,
      };
    });

    if (chartTracking) chartTracking.destroy();
    chartTracking = new Chart(document.getElementById("chart-tracking"), {
      type: "line",
      data: { labels: allDates, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 11 } } },
          tooltip: {
            backgroundColor: "#10182B",
            titleColor: "#ffffff",
            bodyColor: "#e5e7eb",
            padding: 10,
            cornerRadius: 8,
            usePointStyle: true,
            callbacks: {
              title: (items) => `Fecha: ${items[0].label}`,
              label: (item) => ` ${item.dataset.label}: S/ ${item.formattedValue}`,
            },
          },
        },
        scales: { y: { beginAtZero: false } },
      },
    });
  }

  function renderPieCharts(history, products) {
    const container = document.getElementById("pie-charts");
    container.innerHTML = "";
    pieCharts.forEach(c => c.destroy());
    pieCharts = [];

    products.forEach(product => {
      const rows = history.filter(r => r.product === product);
      const byRetail = {};
      rows.forEach(r => { byRetail[r.retail] = r.price; }); // último precio visto en el rango
      const labels = Object.keys(byRetail);
      if (!labels.length) return;

      const item = document.createElement("div");
      item.className = "pie-item";
      item.innerHTML = `<div class="pie-title">${product}</div><div class="chart-card-body"><canvas></canvas></div>`;
      container.appendChild(item);

      const chart = new Chart(item.querySelector("canvas"), {
        type: "pie",
        data: {
          labels,
          datasets: [{
            data: labels.map(l => byRetail[l]),
            backgroundColor: labels.map((l, i) => retailColorFor(l, i)),
          }],
        },
        options: {
          maintainAspectRatio: false,
          plugins: { legend: { position: "bottom", labels: { boxWidth: 9, font: { size: 10 } } } },
        },
      });
      pieCharts.push(chart);
    });
  }

  function renderByRetailChart(history, products) {
    const retails = Array.from(new Set(history.map(r => r.retail)));
    const datasets = products.map((p, i) => {
      const rows = history.filter(r => r.product === p);
      const latestByRetail = {};
      rows.forEach(r => { latestByRetail[r.retail] = r.price; });
      return {
        label: p,
        data: retails.map(r => latestByRetail[r] ?? 0),
        backgroundColor: palette(i),
      };
    });

    if (chartByRetail) chartByRetail.destroy();
    chartByRetail = new Chart(document.getElementById("chart-by-retail"), {
      type: "bar",
      data: { labels: retails, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 11 } } },
          tooltip: {
            backgroundColor: "#10182B",
            titleColor: "#ffffff",
            bodyColor: "#e5e7eb",
            padding: 10,
            cornerRadius: 8,
            callbacks: {
              label: (item) => ` ${item.dataset.label}: S/ ${item.formattedValue}`,
            },
          },
        },
      },
    });
  }

  init();
})();
