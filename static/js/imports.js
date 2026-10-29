(function () {
  const csCategory = createChipSelect(document.getElementById("f-category"), { placeholder: "Select Category..." });
  const csBrand = createChipSelect(document.getElementById("f-brand"), { placeholder: "Select Brands..." });
  const csImporter = createChipSelect(document.getElementById("f-importer"), { placeholder: "Select Importer..." });
  const tableWrap = document.getElementById("table-wrap");
  const pagination = document.getElementById("pagination");
  const rangeButtons = document.querySelectorAll(".range-btn");

  let days = 7;
  let lastRows = [];

  async function init() {
    await populateChipSelect(csCategory, "/api/categories/imports");
    // Cambiar la categoría solo refresca las opciones de Brands/Importers
    // disponibles para esa categoría — no dispara la búsqueda por sí solo.
    csCategory.onChange(refreshDependentFilters);
    await refreshDependentFilters();
    search(1);
  }

  async function refreshDependentFilters() {
    const catParams = new URLSearchParams();
    appendListParam(catParams, "categoryIds", csCategory.getValues());
    await populateChipSelect(csBrand, `/api/imports/brands?${catParams.toString()}`);
    await populateChipSelect(csImporter, `/api/imports/importers?${catParams.toString()}`);
  }

  rangeButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      rangeButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      days = Number(btn.dataset.days);
      // Solo marca el rango activo — hay que presionar "Search" para
      // aplicarlo, igual que cualquier otro filtro.
    });
  });

  document.getElementById("btn-search").addEventListener("click", () => search(1));
  document.getElementById("btn-export").addEventListener("click", exportXlsx);

  async function search(page) {
    const params = new URLSearchParams();
    appendListParam(params, "categoryIds", csCategory.getValues());
    appendListParam(params, "brandIds", csBrand.getValues());
    appendListParam(params, "importerIds", csImporter.getValues());

    const from = new Date();
    from.setDate(from.getDate() - days);
    params.set("fromDate", localDateISO(from));
    params.set("page", page);
    params.set("size", 50);

    const { data, meta } = await fetchJSON(`/api/imports/?${params.toString()}`);
    lastRows = data;

    renderTable(tableWrap, [
      { key: "date", label: "Date" },
      { key: "category", label: "Category" },
      { key: "brand", label: "Brand" },
      { key: "productCode", label: "Product" },
      { key: "importer", label: "Importer" },
      { key: "aduanaCode", label: "Aduana Code" },
      { key: "cost", label: "Fob Unit", render: r => Number(r.cost).toFixed(2) },
      { key: "quantity", label: "Quantity" },
      { key: "amount", label: "Amount", render: r => r.amount.toFixed(2) },
    ], data);

    renderPagination(pagination, meta, search);
  }

  function exportXlsx() {
    if (!lastRows.length) return;
    const ws = XLSX.utils.json_to_sheet(lastRows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Imports");
    XLSX.writeFile(wb, "imports_export.xlsx");
  }

  init();
})();
