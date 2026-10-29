"""rescore_cruce.py - Re-puntua el cruce Promart->Sodimac desde la cache usando la
marca como FILTRO DURO y peso por rareza de token (IDF).

- Solo compiten candidatos cuya marca coincide con la del producto Promart.
- El score pondera tokens raros (distintivos) mas que genericos (BLANCO, ONE...).
- Si ningun candidato comparte marca -> 'sin-marca' (guarda mejor candidato global).

No hace peticiones: lee .cruce_promart_cache.json + mapeo_promart_por_sku.csv.
Salida: cruce_promart_sodimac_v2.csv
"""
import csv
import io
import json
import math
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = Path(r"C:\Users\HP76530024-EXT\Documents\WebPricing")
CACHE = BASE / ".cruce_promart_cache.json"
INPUT = BASE / "mapeo_promart_por_sku.csv"
OUT = BASE / "cruce_promart_sodimac_v2.csv"

STOP = {"blanco", "negro", "azul", "rojo", "verde", "gris", "cafe", "con", "para",
        "los", "las", "de", "del", "por", "sin", "modelo", "nuevo", "plus",
        "color", "mm", "cm", "pulgadas", "unidad", "unidades", "pack", "tipo",
        "the", "and"}
BRANDS_GENERIC = {"generico", "generica", "genérico", "universal", "sinmarca", ""}


def tokens(s):
    return set(t for t in re.sub(r"[^A-Za-z0-9 ]", " ", str(s or "").upper()).split()
               if len(t) > 2 and t.lower() not in STOP and not t.isdigit())


def bnorm(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def brand_match(pm, cm):
    a, b = bnorm(pm), bnorm(cm)
    if not a or not b or a in BRANDS_GENERIC or b in BRANDS_GENERIC:
        return False
    return a == b or a in b or b in a


def query_for(nombre, marca):
    toks = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", nombre) if t.lower() not in STOP]
    toks = [t for t in toks if not re.fullmatch(r"\d+X\d+[A-Z]*", t.upper())]
    q = " ".join(([marca] if marca else []) + toks[:4])
    return q if q else (toks[0] if toks else "")


def main():
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    filas = list(csv.DictReader(open(INPUT, encoding="utf-8-sig")))
    filas = [f for f in filas if f["estado"] == "ok"]

    # 1) document frequency de tokens sobre TODOS los candidatos en cache
    df = {}
    total_docs = 0
    for info in cache.values():
        for c in info.get("results", []):
            total_docs += 1
            for t in tokens(c["name"] + " " + c["brand"]):
                df[t] = df.get(t, 0) + 1

    def idf(t):
        return math.log((total_docs + 1) / (df.get(t, 0) + 1)) + 0.5

    def score(promart_tok, cand):
        common = promart_tok & tokens(cand["name"] + " " + cand["brand"])
        s = sum(idf(t) for t in common)
        dim = re.search(r"(\d+X\d+\.?\d*)", promart_tok_name.upper(), re.I)
        return s, sorted(common)

    out_rows = []
    for f in filas:
        info = cache.get("cr:" + f["sku_excel"], {})
        results = info.get("results", [])
        pm = f["marca"]
        pm_tok = tokens(f["nombre_promart"] + " " + pm)
        global promart_tok_name
        promart_tok_name = f["nombre_promart"]

        best_brand = None
        best_any = None
        sku_hit = None
        for c in results:
            sc, cm = score(pm_tok, c)
            if best_any is None or sc > best_any[0]:
                best_any = (sc, cm, c)
            if c["skuId"] in (f["sku_sodimac_1"], f["sku_sodimac_2"]) and c["skuId"]:
                if sku_hit is None or sc > sku_hit[0]:
                    sku_hit = (sc, cm, c)
            if brand_match(pm, c["brand"]):
                if best_brand is None or sc > best_brand[0]:
                    best_brand = (sc, cm, c)

        if sku_hit:
            sc, cm, c = sku_hit
            match = "sku-exacto"
            src = "skuId-excel"
        elif best_brand:
            sc, cm, c = best_brand
            distinctive = [t for t in cm if df.get(t, 0) > 0 and idf(t) > 1.0]
            if len(distinctive) >= 2:
                match = "ok"
            elif len(distinctive) == 1:
                match = "dudoso"
            else:
                match = "sin-match"
            src = "marca+score"
        else:
            if best_any:
                sc, cm, c = best_any
                match = "sin-marca"
                src = "mejor-global"
            else:
                sc, cm, c = 0.0, [], {"name": "", "brand": "", "skuId": "", "productId": ""}
                match = "sin-resultados"
                src = "n/a"

        out_rows.append([f["area"], f["sku_excel"], f["descripcion_excel"], pm, f["ean"],
                         f["ean_valido"], info.get("query", ""), len(results),
                         c["name"], c["brand"], c["skuId"], c["productId"],
                         "%.2f" % sc, ";".join(cm), src, match])

    cols = ["area", "sku_excel", "descripcion_excel", "marca", "ean", "ean_valido",
            "query", "n_resultados", "candidato_nombre", "candidato_brand",
            "candidato_skuId", "candidato_productId", "score", "tokens_compartidos",
            "fuente", "match"]
    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(out_rows)

    from collections import Counter
    cnt = Counter(r[-1] for r in out_rows)
    print("total:", len(out_rows))
    for k, v in cnt.most_common():
        print("  %-14s %d" % (k, v))
    print("csv:", OUT)


if __name__ == "__main__":
    main()