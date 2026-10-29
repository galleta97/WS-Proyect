(function () {
  const csRetail = createChipSelect(document.getElementById("f-retail"), { placeholder: "Select Retail..." });
  const csBrand = createChipSelect(document.getElementById("f-brand"), { placeholder: "Select Brand..." });
  const tableWrap = document.getElementById("table-wrap");
  const pagination = document.getElementById("pagination");

  let lastRows = [];

  async function init() {
    await populateChipSelect(csRetail, "/api/retails/");
    await populateChipSelect(csBrand, "/api/web-home/brands");
    // Sin auto-búsqueda al cambiar filtros — solo el botón "Search" dispara
    // la consulta (igual que en Imports y Search).
    search(1);
  }

  document.getElementById("btn-search").addEventListener("click", () => search(1));
  document.getElementById("btn-export").addEventListener("click", exportXlsx);

  async function search(page) {
    const params = new URLSearchParams();
    appendListParam(params, "retailIds", csRetail.getValues());
    appendListParam(params, "brandIds", csBrand.getValues());
    params.set("page", page);
    params.set("size", 20);

    const { data, meta } = await fetchJSON(`/api/web-home/prices?${params.toString()}`);
    lastRows = data;

    renderTable(tableWrap, [
      { key: "date", label: "Date" },
      { key: "retail", label: "Retail" },
      { key: "brand", label: "Brand" },
      { key: "product", label: "Product" },
      { key: "actual", label: "Actual", render: r => r.actual != null ? `S/ ${r.actual.toFixed(2)}` : "—" },
      { key: "offer", label: "Offer", render: r => r.offer != null ? `S/ ${r.offer.toFixed(2)}` : "—" },
      { key: "normal", label: "Normal", render: r => r.normal != null ? `S/ ${r.normal.toFixed(2)}` : "—" },
      { key: "discounts", label: "Discounts" },
      { key: "description", label: "Description" },
    ], data);

    renderPagination(pagination, meta, search);
  }

  function exportXlsx() {
    if (!lastRows.length) return;
    const ws = XLSX.utils.json_to_sheet(lastRows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "WebHomePrices");
    XLSX.writeFile(wb, "web_home_prices_export.xlsx");
  }

  init();
})();
