"""validar_sku_sodimac.py - Verifica si los 'Sku sodimac 1/2' del excel (Lista KVIs)
resuelven como skuId reales de SODIMAC y si corresponden al mismo producto que el
SKU Promart mapeado (por nombre/marca).

Metodo: por cada producto, consulta el buscador de Sodimac con la marca + tokens
del nombre Promart y (a) comprueba si el skuId del excel aparece en los resultados,
(b) anota el nombre/brand del candidato para comparar manualmente.

Salida: validacion_sku_sodimac.csv + reporte de cobertura.

Uso:
  python validar_sku_sodimac.py --limit 10
  python validar_sku_sodimac.py
"""
import argparse
import csv
import io
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\HP76530024-EXT\Documents\Default Project")

from scrapers.vtex_stores import DEFAULT_HEADERS

BUSCAR = "https://www.sodimac.com.pe/sodimac-pe/buscar/?Ntt=%s"
CACHE = Path(__file__).with_name(".valida_sodimac_cache.json")
OUT = Path(__file__).with_name("validacion_sku_sodimac.csv")
INPUT = Path(__file__).with_name("mapeo_promart_por_sku.csv")
DELAY = 0.5


def cargar():
    filas = list(csv.DictReader(open(INPUT, encoding="utf-8-sig")))
    out = []
    for f in filas:
        if f["estado"] != "ok":
            continue
        for col, dest in (("sku_sodimac_1", "sod1"), ("sku_sodimac_2", "sod2")):
            v = f.get(col, "").strip()
            if not v:
                continue
            out.append({
                "area": f["area"], "sku_excel": f["sku_excel"],
                "col": dest, "sku_sodimac": v,
                "nombre_promart": f["nombre_promart"], "marca": f["marca"],
                "ean": f["ean"], "ean_valido": f["ean_valido"],
                "desc_excel": f["descripcion_excel"],
            })
        if not f.get("sku_sodimac_1", "").strip() and not f.get("sku_sodimac_2", "").strip():
            out.append({
                "area": f["area"], "sku_excel": f["sku_excel"],
                "col": "-", "sku_sodimac": "",
                "nombre_promart": f["nombre_promart"], "marca": f["marca"],
                "ean": f["ean"], "ean_valido": f["ean_valido"],
                "desc_excel": f["descripcion_excel"],
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


STOP = re.compile(r"\b(blanco|negro|azul|rojo|verde|amarillo|marron|gris|cafe|larga|verde)\b", re.I)


def query_for(nombre, marca):
    """Query de busqueda: marca + hasta 2 tokens propios del nombre (no genericos)."""
    toks = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", nombre)
    stop = {"blanco", "negro", "azul", "rojo", "verde", "gris", "cafe", "con", "para",
            "los", "las", "de", "del", "modelo", "plus", "pro", "universal"}
    propios = [t for t in toks if t.lower() not in stop]
    q = " ".join(([marca] if marca else []) + propios[:3])
    return q.strip() or (marca or toks[0] if toks else "")


def buscar(q):
    r = requests.get(BUSCAR % requests.utils.quote(q), headers=DEFAULT_HEADERS, timeout=30)
    if r.status_code != 200:
        return {"estado": "http-%d" % r.status_code, "results": []}
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', r.text, re.S)
    if not m:
        return {"estado": "sin-json", "results": []}
    pp = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
    res = pp.get("results") or []
    return {"estado": "ok", "results": [{
        "productId": str(it.get("productId") or ""),
        "skuId": str(it.get("skuId") or ""),
        "name": re.sub(r"\s+", " ", str(it.get("displayName") or "")).strip(),
        "brand": str(it.get("brand") or "").strip()} for it in res]}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    a = p.parse_args(argv)
    filas = cargar()
    if a.limit:
        filas = filas[:a.limit]
    print("pares a validar:", len(filas))

    cache = cargar_cache()
    pend = [f for f in filas if (f["sku_sodimac"] and "sod:" + f["sku_sodimac"] not in cache)]
    print("  pendientes:", len(pend))
    for i, f in enumerate(pend, 1):
        cache["sod:" + f["sku_sodimac"]] = buscar(query_for(f["nombre_promart"], f["marca"]))
        if i % 20 == 0:
            guardar_cache(cache)
            print("    %d/%d" % (i, len(pend)))
        time.sleep(DELAY)
    guardar_cache(cache)

    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["area", "sku_excel", "col", "sku_sodimac", "marca", "ean",
                    "ean_valido", "match_por_sku", "match_por_nombre", "n_resultados",
                    "nombre_promart", "candidato_sodimac"])
        for f in filas:
            if not f["sku_sodimac"]:
                w.writerow([f["area"], f["sku_excel"], "-", "", f["marca"], f["ean"],
                            f["ean_valido"], "", "", "", f["nombre_promart"], "(sin sku sodimac)"])
                continue
            info = cache.get("sod:" + f["sku_sodimac"], {"results": []})
            by_sku = None
            for it in info.get("results", []):
                if it["skuId"] == f["sku_sodimac"]:
                    by_sku = it
                    break
            # match por nombre/brand: mismo productId o skuId -> es el mismo
            match_nombre = ""
            n = len(info.get("results", []))
            cand = by_sku if by_sku else ((info.get("results")[:1] or [{}])[0])
            cand_name = cand.get("name", "") if isinstance(cand, dict) else ""
            w.writerow([f["area"], f["sku_excel"], f["col"], f["sku_sodimac"],
                        f["marca"], f["ean"], f["ean_valido"],
                        "si" if by_sku else "no",
                        match_nombre, n,
                        f["nombre_promart"], cand_name])
    print("csv: %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())