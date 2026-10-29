"""
rellenar_hueco.py - rellena el hueco 2026-10-07 .. 2026-10-11 con una serie de
precios ESTIMADA (demo) continua, anclada en la última captura real anterior
(2026-10-06) y con el mismo estilo de `seed_demo_history`.

No inventa productos ni tiendas: parte de las filas REALES del 2026-10-06 (o la
fecha real más reciente previa al hueco) y genera hacia ADELANTE día a día con
un paso diario de ±5%, redondeando a decenas de sol; precio_lista y
precio_tarjeta mantienen la proporción de la fila real.

El hueco queda rellenado y los datos REALES (10-06 y 10-12 tras el refresh)
quedan intactos. Para borrar lo generado: --reset con el mismo rango (NO borra
fechas reales).

Uso:
  python rellenar_hueco.py --dry-run
  python rellenar_hueco.py                # 2026-10-07 .. 2026-10-11
  python rellenar_hueco.py --from 2026-10-07 --to 2026-10-11 --reset
"""

import argparse
import random
import sqlite3
import sys
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DB_PATH = Path(__file__).with_name("precios.db")

DEFAULT_DESDE = date(2026, 10, 7)
DEFAULT_HASTA = date(2026, 10, 11)
PASO_DIARIO = 0.05          # ±5% por día (igual que seed_demo_history)
REDONDEO = Decimal("10")    # a decenas de sol


def redondear(v):
    return float(Decimal(str(v)).quantize(REDONDEO, rounding=ROUND_HALF_UP))


def ancla_real(con, categoria_id):
    """Una fila base por (product_code, retail_id): la más reciente real ANTES
    del hueco. Devuelve (lista_filas, fecha_ancla)."""
    sql = """
        SELECT e.*
        FROM price_entries e
        WHERE e.category_id = ? AND e.date = (
              SELECT MAX(e2.date) FROM price_entries e2
              WHERE e2.category_id = e.category_id AND e2.retail_id = e.retail_id
                AND e2.product_code = e.product_code
                AND e2.date < ?
          )
    """
    candidatas = con.execute(sql, (categoria_id, DEFAULT_DESDE.isoformat())).fetchall()
    if not candidatas:
        return [], None
    ancla_fecha = max(r["date"] for r in candidatas)
    mejor = {}
    for r in candidatas:
        if float(r["min_price"]) <= 0:
            continue
        k = (r["product_code"], r["retail_id"])
        prev = mejor.get(k)
        if prev is None or float(r["min_price"]) < float(prev["min_price"]):
            mejor[k] = r
    return list(mejor.values()), ancla_fecha


def serie(ancla, dias, rnd):
    """Serie hacia adelante. Devuelve {fecha: precio}."""
    precios = {}
    actual = float(ancla)
    for fecha in dias:
        paso = rnd.uniform(-PASO_DIARIO, PASO_DIARIO)
        actual = actual * (1 + paso)
        if actual < 1:
            actual = float(ancla)
        precios[fecha] = redondear(actual)
    return precios


def main(argv=None):
    p = argparse.ArgumentParser(description="Rellena el hueco 07-11-2026 con demo")
    p.add_argument("--from", dest="desde", default=DEFAULT_DESDE.isoformat())
    p.add_argument("--to", dest="hasta", default=DEFAULT_HASTA.isoformat())
    p.add_argument("--reset", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--seed", type=int, default=20261007)
    a = p.parse_args(argv)

    desde = date.fromisoformat(a.desde)
    hasta = date.fromisoformat(a.hasta)
    if desde >= hasta:
        p.error("--from debe ser anterior a --to")
    if desde < DEFAULT_DESDE or hasta > DEFAULT_HASTA:
        p.error("el script solo rellena dentro de %s..%s (datos reales alrededor)"
                % (DEFAULT_DESDE, DEFAULT_HASTA))

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    cat = con.execute("SELECT id FROM categories WHERE code='TELEVISORES'").fetchone()
    if cat is None:
        p.error("no existe la categoria TELEVISORES")
    cat_id = cat["id"]

    dias = []
    d = desde
    while d <= hasta:
        dias.append(d)
        d += timedelta(days=1)

    anclas, fecha_ancla = ancla_real(con, cat_id)
    print("Relleno demo: %s -> %s  (%d días)" % (desde, hasta, len(dias)))
    print("  ancla en la captura real: %s" % fecha_ancla)
    print("  series a generar : %d  (%d productos x %d tiendas)"
          % (len(anclas), len({r['product_code'] for r in anclas}),
             len({r['retail_id'] for r in anclas})))
    print("  filas a insertar : ~%d" % (len(anclas) * len(dias)))

    if a.reset:
        n = con.execute("DELETE FROM price_entries WHERE date BETWEEN ? AND ?",
                        (desde.isoformat(), hasta.isoformat())).rowcount
        con.commit()
        print("  borradas (--reset): %d" % n)

    if a.dry_run:
        print("  --dry-run: no se escribió nada")
        return 0

    rnd = random.Random(a.seed)
    lote = []
    insertadas = 0
    for ancla in anclas:
        precios = serie(float(ancla["min_price"]), dias, rnd)
        ratio_lista = (float(ancla["list_price"]) / float(ancla["min_price"])
                       if ancla["list_price"] and float(ancla["min_price"]) > 0 else None)
        ratio_tarjeta = (float(ancla["card_price"]) / float(ancla["min_price"])
                         if ancla["card_price"] and float(ancla["min_price"]) > 0 else None)
        for fecha in dias:
            v = precios[fecha]
            lote.append((
                fecha.isoformat(), ancla["category_id"], ancla["retail_id"],
                ancla["brand_id"], ancla["product_code"], "%.2f" % v,
                int(ancla["has_sales_rank"] or 0), ancla["sales_rank"],
                ancla["is_available"], ancla["seller"],
                ("%.2f" % redondear(v * ratio_lista)) if ratio_lista else None,
                ("%.2f" % redondear(v * ratio_tarjeta)) if ratio_tarjeta else None,
                ancla["listing_ref"], ancla["name"], ancla["ean"], ancla["url"],
            ))
            if len(lote) >= 5000:
                con.executemany("""
                    INSERT INTO price_entries
                      (date, category_id, retail_id, brand_id, product_code, min_price,
                       has_sales_rank, sales_rank, is_available, seller, list_price,
                       card_price, listing_ref, name, ean, url)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, lote)
                insertadas += len(lote)
                lote = []
    if lote:
        con.executemany("""
            INSERT INTO price_entries
              (date, category_id, retail_id, brand_id, product_code, min_price,
               has_sales_rank, sales_rank, is_available, seller, list_price,
               card_price, listing_ref, name, ean, url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, lote)
        insertadas += len(lote)
    con.commit()

    print("  insertadas: %d filas" % insertadas)
    print("")
    print("  Los datos REALES (%s en adelante) quedaron intactos." % fecha_ancla)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())