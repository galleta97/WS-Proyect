"""
seed_demo_history.py - genera un histórico de precios DEMO hacia atrás desde
una fecha real, para poder mostrar los gráficos en una presentación.

No inventa productos ni tiendas: parte de las filas REALES que ya están en
`precios.db` y solo les walked-una-serie-de-precios hacia atrás en el tiempo.

    2026-08-04 ......... 2026-10-03   <- generado por este script (demo)
    2026-10-04 .........              <- captura real, no se toca
    2026-10-05 .........              <- captura real (Sodimac corregida)

Cómo se genera cada serie:
  - Se ancla en el precio REAL más reciente de esa tienda (Promart/Metro:
    2026-10-04; Sodimac: 2026-10-05, que ya está corregido).
  - Hacia atrás, día por día, con un paso diario de ±5% (el mismo rango que
    usa `price_updater._simulate_one_price_update`) y unabagea suave hacia el
    ancla para que la serie no se vaya de controle en 2 meses.
  - Se redondea a decenas de sol: el 99% de los precios reales termina en .00.
  - `precio_lista` y `precio_tarjeta` mantienen la proporción que ya tenía la
    fila real, para que el tooltip siga siendo coherente.

Uso:
  python seed_demo_history.py --dry-run     # muestra el plan, no escribe
  python seed_demo_history.py               # genera el rango por defecto
  python seed_demo_history.py --reset       # borra lo generado y regenera
  python seed_demo_history.py --from 2026-09-01 --to 2026-10-03
"""

import argparse
import random
import sqlite3
import sys
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DB_PATH = Path(__file__).with_name("precios.db")

# A partir de esta fecha los datos son reales: el script nunca escribe ahí.
PRIMERA_FECHA_REAL = date(2026, 10, 4)
PASO_DIARIO = 0.05          # ±5% por día
REVERSION = 0.06            # fuerza con la que la serie vuelve al ancla
REDONDEO = Decimal("10")    # a decenas de sol


def redondear(v):
    return float(Decimal(str(v)).quantize(REDONDEO, rounding=ROUND_HALF_UP))


def construir_anclas(con, categoria_id, hasta):
    """Una fila base por (product_code, retail_id): la más barata con stock."""
    sql = """
        SELECT e.*
        FROM price_entries e
        JOIN retails rt ON rt.id = e.retail_id
        WHERE e.category_id = ? AND e.date = (
              SELECT MAX(e2.date) FROM price_entries e2
              JOIN retails r2 ON r2.id = e2.retail_id
              WHERE e2.category_id = e.category_id AND e2.retail_id = e.retail_id
                AND e2.product_code = e.product_code
          )
          AND e.date >= ?
    """
    candidatas = con.execute(sql, (categoria_id, (hasta - timedelta(days=1)).isoformat())).fetchall()
    mejor = {}
    for r in candidatas:
        if float(r["min_price"]) <= 0:
            continue
        k = (r["product_code"], r["retail_id"])
        prev = mejor.get(k)
        if prev is None or float(r["min_price"]) < float(prev["min_price"]):
            mejor[k] = r
    return list(mejor.values())


def serie(ancla, dias, rnd):
    """Serie de precios hacia atrás. Devuelve [(fecha, precio), ...] orden ascendente."""
    precios = {}
    actual = float(ancla)
    for fecha in dias:                      # dias viene de más reciente a más antigua
        paso = rnd.uniform(-PASO_DIARIO, PASO_DIARIO)
        # pull hacia el ancla: evita que en 2 meses la serie se vaya muy lejos
        correccion = 1.0 + REVERSION * ((float(ancla) / actual - 1.0) if actual else 0)
        actual = actual * (1 + paso) * correccion
        if actual < 1:
            actual = float(ancla)
        precios[fecha] = redondear(actual)
    return precios


def main(argv=None):
    p = argparse.ArgumentParser(description="Histórico de precios demo hacia atrás")
    p.add_argument("--from", dest="desde", default="2026-08-04")
    p.add_argument("--to", dest="hasta", default="2026-10-03")
    p.add_argument("--reset", action="store_true", help="borra lo generado antes")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--seed", type=int, default=20261004, help="semilla (reproducible)")
    a = p.parse_args(argv)

    desde = date.fromisoformat(a.desde)
    hasta = date.fromisoformat(a.hasta)
    if desde >= hasta:
        p.error("--from debe ser anterior a --to")
    if hasta >= PRIMERA_FECHA_REAL:
        p.error("--to (%s) entra en datos REALES (>= %s); el script no escribe ahi"
                % (hasta, PRIMERA_FECHA_REAL))

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    cat = con.execute("SELECT id FROM categories WHERE code='TELEVISORES'").fetchone()
    if cat is None:
        p.error("no existe la categoria TELEVISORES")
    cat_id = cat["id"]

    dias = []
    d = hasta
    while d >= desde:
        dias.append(d)
        d -= timedelta(days=1)
    dias.reverse()   # ascendente

    anclas = construir_anclas(con, cat_id, hasta)
    print("Histórico demo: %s -> %s  (%d días)" % (desde, hasta, len(dias)))
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
        precios = serie(float(ancla["min_price"]), list(reversed(dias)), rnd)
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
                ancla["listing_ref"], ancla["name"], ancla["ean"],
            ))
            if len(lote) >= 5000:
                con.executemany("""
                    INSERT INTO price_entries
                      (date, category_id, retail_id, brand_id, product_code, min_price,
                       has_sales_rank, sales_rank, is_available, seller, list_price,
                       card_price, listing_ref, name, ean)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, lote)
                insertadas += len(lote)
                lote = []
    if lote:
        con.executemany("""
            INSERT INTO price_entries
              (date, category_id, retail_id, brand_id, product_code, min_price,
               has_sales_rank, sales_rank, is_available, seller, list_price,
               card_price, listing_ref, name, ean)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, lote)
        insertadas += len(lote)
    con.commit()

    print("  insertadas: %d filas" % insertadas)
    print("")
    print("  Los datos REALES (%s en adelante) quedaron intactos." % PRIMERA_FECHA_REAL)
    print("  Para borrar lo demo:  python seed_demo_history.py --reset --dry-run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
