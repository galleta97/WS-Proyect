"""cruce_promart_sodimac.py - Cruce definitivo SKU Promart -> mejor candidato en
Sodimac por nombre/marca (NO depende de los 'Sku sodimac' del excel).

Por cada producto Promart (mapeo_promart_por_sku.csv):
  1. Busca en Sodimac con marca + tokens propios del nombre.
  2. Puntua TODOS los resultados contra nombre+marca del Promart.
  3. Elige el mejor candidato y lo califica (marca, tokens, EAN).
  4. Devuelve una fila por área con el match y su score.

Uso: python cruce_promart_sodimac.py [--limit N] [--rebuscar]
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
CACHE = Path(__file__).with_name(".cruce_promart_cache.json")
OUT = Path(__file__).with_name("cruce_promart_sodimac.csv")
INPUT = Path(__file__).with_name("mapeo_promart_por_sku.csv")
DELAY = 0.4
MAX_PAGE = 3  # hasta 3 paginas (144 resultados) por producto

STOP = {"blanco", "negro", "azul", "rojo", "verde", "gris", "cafe", "con", "para",
        "los", "las", "de", "del", "por", "sin", "tras", "modelo", "nuevo", "plus",
        "pro", "smart", "color", "milimetros", "mm", "cm", "pulgadas", "unidad", "pack"}


def tokens(s):
    return set(t for t in re.sub(r"[^A-Za-z0-9 ]", " ", str(s or "").upper()).split()
               if len(t) > 2 and t not in STOP and not t.isdigit())


def query_for(nombre, marca):
    toks = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", nombre) if t.lower() not in STOP]
    # quitar parametros de tamaño genericos tipo 68x195X16 o 1POZA
    toks = [t for t in toks if not re.fullmatch(r"\d+X\d+[A-Z]*", t.upper())]
    q = " ".join(([marca] if marca else []) + toks[:4])
    return (q or toks[0]) if (q or toks) else ""


def score(promart, cand):
    """Puntua un candidato de Sodimac contra el producto Promart. Mayor = mejor."""
    s = 0.0
    nb = tokens(promart["nombre"] + " " + promart["marca"])
    cn = tokens(cand["name"] + " " + cand["brand"])
    common = nb & cn
    # marca exacta pesa mucho
    if promart["marca"] and cand["brand"]:
        ma = re.sub(r"[^A-Z]", "", promart["marca"].upper())
        cb = re.sub(r"[^A-Z]", "", cand["brand"].upper())
        if ma and cb:
            if ma == cb:
                s += 3.0
            elif ma in cb or cb in ma:
                s += 1.5
    # tokens compartidos
    s += 2.0 * len(common)
    # dims/medidas: ej 68x17.5
    dim = re.search(r"(\d+X\d+\.?\d*)", promart["nombre"].upper(), re.I)
    cdim = re.search(r"(\d+X\d+\.?\d*)", cand["name"].upper(), re.I)
    if dim and cdim:
        if dim.group(1) == cdim.group(1):
            s += 1.0
    # nombres de familia (la primera palabra no-generica del nombre Promart)
    fam = re.match(r"([A-Za-z][A-Za-z ]{2,20}?)", promart["nombre"])
    return s, sorted(common)


def cargar_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def guardar_cache(cache):
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def buscar_paginado(q):
    res = {}
    for page in range(1, MAX_PAGE + 1):
        url = "%s?page=%d" % (BUSCAR % requests.utils.quote(q), page)
        try:
            r = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
            if r.status_code != 200:
                break
            m = re.search(r'id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', r.text, re.S)
            if not m:
                break
            pp = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
            items = pp.get("results") or []
            total = (pp.get("pagination") or {}).get("count")
            if total is None:
                total = len(items) if not res else None
            for it in items:
                pid = str(it.get("productId") or "")
                if pid and pid not in res:
                    res[pid] = {"productId": pid, "skuId": str(it.get("skuId") or ""),
                                "name": re.sub(r"\s+", " ", str(it.get("displayName") or "")).strip(),
                                "brand": str(it.get("brand") or "").strip()}
            if not items:
                break
            if total and len(res) >= int(total):
                break
        except Exception:  # noqa: BLE001
            break
        time.sleep(0.35)
    return {"estado": "ok", "total": total if "total" in dir() else None,
            "results": list(res.values())}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    a = p.parse_args(argv)

    filas = list(csv.DictReader(open(INPUT, encoding="utf-8-sig")))
    filas = [f for f in filas if f["estado"] == "ok"]
    if a.limit:
        filas = filas[:a.limit]
    print("productos Promart a cruzar:", len(filas), flush=True)

    cache = cargar_cache()
    pend = [f for f in filas if "cr:" + f["sku_excel"] not in cache]
    print("  en cache: %d | pendientes: %d" % (len(filas) - len(pend), len(pend)), flush=True)
    for i, f in enumerate(pend, 1):
        q = query_for(f["nombre_promart"], f["marca"])
        info = buscar_paginado(q)
        info["query"] = q
        cache["cr:" + f["sku_excel"]] = info
        guardar_cache(cache)
        if i % 10 == 0 or i == len(pend):
            print("    %d/%d  (ult: '%s' -> %d res)" % (i, len(pend), q, len(info["results"])), flush=True)
        time.sleep(DELAY)
    guardar_cache(cache)

    # ---- escribir csv ----
    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["area", "sku_excel", "descripcion_excel", "marca", "ean",
                    "ean_valido", "query", "n_resultados",
                    "candidato_nombre", "candidato_brand", "candidato_skuId",
                    "candidato_productId", "score", "marca_ok", "tokens_compartidos", "match"])
        for f in filas:
            info = cache.get("cr:" + f["sku_excel"], {})
            results = info.get("results", [])
            promart = {"nombre": f["nombre_promart"], "marca": f["marca"]}
            best = None
            for c in results:
                sc, cm = score(promart, c)
                if best is None or sc > best[0]:
                    best = (sc, cm, c)
            marca_ok = "no"
            if best:
                sc, cm, c = best
                if f["marca"] and c["brand"]:
                    ma = re.sub(r"[^A-Z]", "", f["marca"].upper())
                    cb = re.sub(r"[^A-Z]", "", c["brand"].upper())
                    marca_ok = "si" if (ma and cb and (ma == cb or ma in cb or cb in ma)) else "no"
                if c["skuId"] in (f["sku_sodimac_1"], f["sku_sodimac_2"]):
                    match = "sku-exacto"
                elif sc >= 2.0:
                    match = "ok"
                elif sc >= 1.0:
                    match = "dudoso"
                else:
                    match = "sin-match"
                w.writerow([f["area"], f["sku_excel"], f["descripcion_excel"],
                            f["marca"], f["ean"], f["ean_valido"],
                            info.get("query", ""), len(results),
                            c["name"], c["brand"], c["skuId"], c["productId"],
                            "%.2f" % sc, marca_ok, ";".join(cm), match])
            else:
                w.writerow([f["area"], f["sku_excel"], f["descripcion_excel"],
                            f["marca"], f["ean"], f["ean_valido"],
                            info.get("query", ""), 0, "", "", "", "", "0", "no", "", "sin-resultados"])
    print("csv: %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())