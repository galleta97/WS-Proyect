"""mapear_promart_por_sku.py - Resuelve los SKUs del excel Lista KVIs contra la
API de Promart (los SKUs de col B son los skuId/itemId de Promart) y extrae
nombre, marca, EAN (con validacion) y codigo de modelo, para poder mapear
Promart contra Sodimac y el resto con el match por modelo de siempre.

El SKU es SOLO el punto de partida (identidad en Promart); el match sigue
siendo por modelo/EAN. Salida:
  1. CSV mapeo_promart_por_sku.csv  (1 fila por SKU)
  2. reporte por pantalla (cobertura)

Uso:
  python mapear_promart_por_sku.py            # completo (299)
  python mapear_promart_por_sku.py --limit 6  # prueba
"""
import argparse
import csv
import io
import json
import sys
import time
from pathlib import Path

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\HP76530024-EXT\Documents\Default Project")
sys.path.insert(0, r"C:\Users\HP76530024-EXT\Documents")

from scrapers import vtex_stores as vx

PROMART_SEARCH = "https://www.promart.pe/api/catalog_system/pub/products/search/"
CACHE = Path(__file__).with_name(".mapeo_promart_cache.json")
OUT = Path(__file__).with_name("mapeo_promart_por_sku.csv")
XLSX = r"C:\Users\HP76530024-EXT\Downloads\KVIs\Lista KVIs.xlsx"
DELAY = 0.35  # pausa entre SKUs (la API Promart limita rafagas)


def cargar_skus():
    import openpyxl
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["KVIs"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    h = rows[0]
    out = []
    for r in rows[1:]:
        if not r or not any(r):
            continue
        d = dict(zip(h, r))
        if d["SKU"] in (None, ""):
            continue
        out.append({
            "area": str(d["Área"] or "").strip(),
            "sku_excel": str(d["SKU"]).strip(),
            "desc_excel": str(d.get("Descripción ") or "").strip(),
            "sku_sod1": (str(d.get("Sku sodimac 1")).strip() if d.get("Sku sodimac 1") not in (None, "") else ""),
            "sku_sod2": (str(d.get("Sku sodimac 2")).strip() if d.get("Sku sodimac 2") not in (None, "") else ""),
        })
    return out


def cargar_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def guardar_cache(cache):
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def fetch_sku(sku):
    """Consulta la API Promart por skuId. Devuelve dict o None."""
    url = PROMART_SEARCH + "?fq=skuId:%s" % sku
    last = None
    for i in range(3):
        try:
            r = requests.get(url, headers=vx.DEFAULT_HEADERS, timeout=25)
            if r.status_code == 200:
                data = r.json()
                if not data:
                    return {"estado": "sin-json"}
                return {"estado": "ok", "product": data[0]}
            last = "http-%d" % r.status_code
        except Exception as exc:  # noqa: BLE001
            last = type(exc).__name__
        time.sleep(1.5 * (i + 1))
    return {"estado": "error", "detalle": last}


def extraer(product):
    """Nombre, marca, EAN valido, modelo, link de un product de la API Promart."""
    name = product.get("productName") or ""
    brand = (product.get("brand") or "").strip()
    link = product.get("linkText") or ""
    pid = product.get("productId") or ""
    ean = None
    eans = set()
    items = product.get("items") or []
    for it in items:
        for k in ("ean", "EAN", "eanIsBatch"):
            v = it.get(k)
            if v:
                eans.add(str(v))
    # el EAN real suele venir en todos los items igual
    for e in eans:
        if _valid_ean(e):
            ean = e
            break
    modelo = vx._model_code(name)
    return {"nombre": name, "marca": brand, "link": link, "pid": pid,
            "ean": ean or (";".join(sorted(eans)) if eans else ""),
            "ean_ok": bool(ean), "modelo": modelo or ""}


def _valid_ean(code):
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(digits) != 13 or digits.startswith("2"):
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == int(digits[12])


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    a = p.parse_args(argv)

    skus = cargar_skus()
    if a.limit:
        skus = skus[:a.limit]
    print("SKUs a resolver: %d" % len(skus))

    cache = cargar_cache()
    pend = [s for s in skus if "sku:" + s["sku_excel"] not in cache]
    print("  en cache: %d | pendientes: %d" % (len(skus) - len(pend), len(pend)))

    for i, s in enumerate(pend, 1):
        cache["sku:" + s["sku_excel"]] = fetch_sku(s["sku_excel"])
        if i % 25 == 0:
            guardar_cache(cache)
            print("    %d/%d" % (i, len(pend)))
        time.sleep(DELAY)
    guardar_cache(cache)

    # ---- escribir csv ----
    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["area", "sku_excel", "descripcion_excel", "sku_sodimac_1",
                    "sku_sodimac_2", "nombre_promart", "marca", "ean",
                    "ean_valido", "modelo", "link", "estado"])
        for s in skus:
            info = cache.get("sku:" + s["sku_excel"], {})
            if info.get("estado") != "ok":
                w.writerow([s["area"], s["sku_excel"], s["desc_excel"],
                            s["sku_sod1"], s["sku_sod2"], "", "", "", "", "", "",
                            info.get("estado", "") + (" " + str(info.get("detalle", "")) if info.get("detalle") else "")])
                continue
            e = extraer(info["product"])
            w.writerow([s["area"], s["sku_excel"], s["desc_excel"],
                        s["sku_sod1"], s["sku_sod2"], e["nombre"], e["marca"],
                        e["ean"], "si" if e["ean_ok"] else "no", e["modelo"],
                        e["pid"] + "-" + e["link"], "ok"])
    print("csv: %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())