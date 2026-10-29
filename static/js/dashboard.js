(function () {
  const fmtInt = n => Number(n).toLocaleString("es-PE");
  const fmtMoney = n => "S/ " + Number(n).toLocaleString("es-PE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const STATUS = {
    CRITICO: '<span class="tag tag-red">Crítico</span>',
    BAJO: '<span class="tag tag-amber">Bajo</span>',
  };
  const POSITION = {
    mas_caro: '<span class="tag tag-gray">Más caro</span>',
    mas_barato: '<span class="tag tag-green">Más barato</span>',
    igual_mercado: '<span class="tag tag-gray">Precio de mercado</span>',
  };

  let lowRows = [];

  function plural(n, one, many) { return `${fmtInt(n)} ${n === 1 ? one : many}`; }

  function renderKpis(k) {
    document.getElementById("kpi-active").textContent = fmtInt(k.activeProducts);
    document.getElementById("kpi-active-sub").textContent = "en " + plural(k.categories, "categoría", "categorías");
    document.getElementById("kpi-low").textContent = fmtInt(k.belowMin);
    document.getElementById("kpi-expensive").textContent = fmtInt(k.moreExpensive);
    document.getElementById("kpi-expensive-sub").textContent =
      k.compared ? `de ${plural(k.compared, "producto comparado", "productos comparados")}` : "sin precios de competencia";
    document.getElementById("kpi-moves").textContent = fmtInt(k.movementsToday);
    const parts = [plural(k.exitsToday, "salida", "salidas"), plural(k.entriesToday, "entrada", "entradas")];
    if (k.adjustmentsToday) parts.push(plural(k.adjustmentsToday, "ajuste", "ajustes"));
    document.getElementById("kpi-moves-sub").textContent = parts.join(" · ");
  }

  function renderLow(rows) {
    const wrap = document.getElementById("low-wrap");
    if (!rows.length) { renderEmpty(wrap, "Ningún producto está en su stock mínimo"); return; }
    wrap.innerHTML = `<table><thead><tr>
        <th>Código</th><th>Producto</th><th class="num">Stock</th><th class="num">Mínimo</th><th>Estado</th>
      </tr></thead><tbody>${rows.map(r => `<tr>
        <td><a class="row-link" href="/inventory?code=${encodeURIComponent(r.code)}" title="Ver kardex">${esc(r.code)}</a></td><td>${esc(r.name)}</td>
        <td class="num">${fmtInt(r.stock)}</td><td class="num">${fmtInt(r.minStock)}</td>
        <td>${STATUS[r.status] || ""}</td></tr>`).join("")}</tbody></table>`;
  }

  function shortName(name) {
    return name.length > 28 ? name.slice(0, 27) + "…" : name;
  }

  function renderRotation(rows) {
    const box = document.getElementById("rotation-box");
    if (!rows.length) { box.innerHTML = '<p class="empty">Aún no hay salidas en los últimos 30 días</p>'; return; }
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#7b6ef6";
    new Chart(document.getElementById("chart-rotation"), {
      type: "bar",
      data: {
        labels: rows.map(r => shortName(r.name)),
        datasets: [{ data: rows.map(r => r.units), backgroundColor: accent, borderRadius: 4, barPercentage: 0.75 }],
      },
      options: {
        indexAxis: "y",
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            title: items => rows[items[0].dataIndex].name,
            label: item => `${fmtInt(item.raw)} unidades vendidas`,
          } },
        },
        scales: {
          x: { beginAtZero: true, grid: { color: "#eef0f4" }, ticks: { precision: 0 } },
          y: { grid: { display: false } },
        },
      },
    });
  }

  function renderComparisons(rows, lastCapture, reference) {
    const wrap = document.getElementById("cmp-wrap");
    document.getElementById("last-capture").textContent = lastCapture
      ? `Última captura: ${lastCapture.split("-").reverse().join("/")}` + (reference ? ` · precio propio = ${reference}` : "")
      : "";
    if (!rows.length) { renderEmpty(wrap, "No hay productos enlazados con precios de la competencia"); return; }
    wrap.innerHTML = `<table><thead><tr>
        <th>Producto</th><th class="num">Precio propio</th><th class="num">Menor precio competencia</th>
        <th>Tienda</th><th class="num">Diferencia</th><th>Posición</th>
      </tr></thead><tbody>${rows.map(r => `<tr>
        <td>${esc(r.name)}<span class="seller-note">${esc(r.code)}</span></td>
        <td class="num">${fmtMoney(r.ownPrice)}</td>
        <td class="num">${fmtMoney(r.competitorPrice)}</td>
        <td>${esc(r.retail)}</td>
        <td class="num">${r.diffPct > 0 ? "+" : ""}${r.diffPct.toFixed(1)} %</td>
        <td>${POSITION[r.position] || ""}</td></tr>`).join("")}</tbody></table>`;
  }

  document.getElementById("btn-export-low").addEventListener("click", () => {
    const ws = XLSX.utils.json_to_sheet(lowRows.map(r => ({
      "Código": r.code, "Producto": r.name, "Stock": r.stock, "Mínimo": r.minStock,
      "Unidad": r.unit, "Estado": r.status === "CRITICO" ? "Crítico" : "Bajo",
    })));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Por agotarse");
    XLSX.writeFile(wb, `productos_por_agotarse_${localDateISO()}.xlsx`);
  });

  fetchJSON("/api/dashboard/summary").then(data => {
    lowRows = data.lowStock;
    renderKpis(data.kpis);
    renderLow(data.lowStock);
    renderRotation(data.rotation);
    renderComparisons(data.comparisons, data.lastCapture, data.referenceRetail);
  }).catch(err => {
    ["low-wrap", "cmp-wrap"].forEach(id => renderEmpty(document.getElementById(id), "No se pudo cargar: " + esc(err.message)));
  });
})();
