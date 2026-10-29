"""
seed_inventory.py - crea las tablas de inventario y carga datos DEMO para el
dashboard y el kardex, sin tocar los precios capturados.

Qué hace:
  1. Respalda la base SQLite (precios.backup-inventario-<fecha>.db).
  2. Crea solo las tablas nuevas (products, suppliers, stock_movements,
     stock_alerts); las existentes no se modifican.
  3. Toma N modelos con precio en la tienda de referencia (PROMART) y en al
     menos otras dos tiendas, y los registra como productos propios: el
     precio de venta es el de la tienda de referencia y el costo, el 82 %.
  4. Simula 30 días de entradas, salidas y ajustes con proveedores ficticios,
     para que el dashboard tenga rotación, alertas y movimientos del día.

Los proveedores y movimientos son ficticios; sirven solo para la demo.

Uso:
  python seed_inventory.py              # carga 40 productos si no hay ninguno
  python seed_inventory.py --n 60       # otra cantidad
  python seed_inventory.py --reset      # borra SOLO los datos de inventario y recarga
"""

import argparse
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from app import create_app
from extensions import db
from inventory import latest_competitor_prices, register_movement
from models import PriceEntry, Product, Retail, StockAlert, StockMovement, Supplier, User
from routes.api import REFERENCE_RETAIL_CODE

SUPPLIERS = [
    ("20999999901", "Distribuidora Andina S.A.C."),
    ("20999999902", "Importaciones del Pacífico S.A.C."),
    ("20999999903", "Electro Mayorista Lima E.I.R.L."),
]
SALE_REASONS = ["Venta mostrador", "Venta mostrador", "Venta mostrador", "Venta web", "Venta corporativa"]


def backup_sqlite(app):
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        return None
    path = Path(uri.replace("sqlite:///", "", 1))
    if not path.exists():
        return None
    dest = path.with_name(f"{path.stem}.backup-inventario-{datetime.now():%Y%m%d_%H%M%S}{path.suffix}")
    shutil.copy2(path, dest)
    return dest


def pick_models(n):
    ref = Retail.query.filter_by(code=REFERENCE_RETAIL_CODE).first()
    if ref is None:
        sys.exit(f"No existe la tienda de referencia {REFERENCE_RETAIL_CODE}.")
    codes = [c for (c,) in db.session.query(PriceEntry.product_code)
             .filter(PriceEntry.retail_id == ref.id).distinct()]
    prices = latest_competitor_prices(codes)
    picked = []
    for code in sorted(codes):
        stores = prices.get(code, {})
        own = stores.get(REFERENCE_RETAIL_CODE)
        others = [v for rc, v in stores.items() if rc != REFERENCE_RETAIL_CODE and v["inStock"]]
        if own and own["inStock"] and len(others) >= 2:
            picked.append((code, own["price"]))
    rng = random.Random(7)
    rng.shuffle(picked)
    return ref, picked[:n]


def product_name(code, ref_id):
    row = (PriceEntry.query.filter_by(product_code=code, retail_id=ref_id)
           .filter(PriceEntry.name.isnot(None))
           .order_by(PriceEntry.date.desc()).first())
    return (row.name if row else code)[:200], row


def simulate(product, user_id, suppliers, rng, start, now, popularity):
    """30 días de movimientos para un producto."""
    def at(day, hour, minute):
        return start + timedelta(days=day, hours=hour, minutes=minute)

    initial = rng.randint(12, 35)
    register_movement(product.id, "AJUSTE", initial, user_id,
                      reason="Inventario inicial", when=at(0, 8, 0), commit=False)
    guide = rng.randint(4000, 4900)
    days = (now - start).days
    for day in range(days + 1):
        # Cada día en orden cronológico: reposición a primera hora, ventas
        # entre las 9 y las 19 y, rara vez, una merma al cierre.
        # La reposición llega cuando el stock está en el mínimo (no siempre a tiempo).
        when = at(day, 8, 30)
        if day and product.stock <= product.min_stock and rng.random() < 0.45 and when < now - timedelta(days=2):
            guide += 1
            register_movement(product.id, "ENTRADA", rng.randint(12, 30), user_id,
                              supplier_id=rng.choice(suppliers).id,
                              reason=f"T001-{guide:06d}", when=when, commit=False)
        hours = sorted(rng.sample(range(9, 20), 4))
        for hour in hours:
            when = at(day, hour, rng.randint(0, 59))
            if when >= now:
                break
            if rng.random() < popularity:
                qty = min(product.stock, rng.choice([1, 1, 1, 2, 2, 3]))
                if qty > 0:
                    register_movement(product.id, "SALIDA", qty, user_id,
                                      reason=rng.choice(SALE_REASONS), when=when, commit=False)
        when = at(day, 20, 15)
        if rng.random() < 0.02 and product.stock > 0 and when < now:
            register_movement(product.id, "AJUSTE", -1, user_id,
                              reason="Producto dañado", when=when, commit=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=40, help="cantidad de productos (por defecto 40)")
    parser.add_argument("--reset", action="store_true", help="borra los datos de inventario antes de cargar")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        has_products = (db.inspect(db.engine).has_table(Product.__tablename__)
                        and Product.query.count() > 0)
        if has_products and not args.reset:
            print("Ya hay productos de inventario. Usa --reset para recargar los datos demo.")
            return

        backup = backup_sqlite(app)
        if backup:
            print(f"Respaldo: {backup.name}")
        db.create_all()  # solo crea las tablas que faltan
        if args.reset:
            for model in (StockAlert, StockMovement, Product, Supplier):
                model.query.delete()
            db.session.commit()

        user = User.query.filter_by(email="demo@vigia.pe").first() or User.query.first()
        if user is None:
            sys.exit("No hay usuarios. Crea una cuenta o ejecuta seed.py primero.")

        ref, models = pick_models(args.n)
        if not models:
            sys.exit("No hay modelos con precio en la tienda de referencia y en otras dos tiendas.")

        suppliers = [Supplier(ruc=r, business_name=name) for r, name in SUPPLIERS]
        db.session.add_all(suppliers)
        db.session.flush()

        rng = random.Random(42)
        now = datetime.now().replace(second=0, microsecond=0)
        start = (now - timedelta(days=30)).replace(hour=0, minute=0)
        for i, (code, price) in enumerate(models, start=1):
            name, row = product_name(code, ref.id)
            product = Product(
                code=f"TV-{i:04d}",
                name=name,
                category_id=row.category_id if row else 1,
                unit="unidad",
                cost=round(price * 0.82, 2),
                sale_price=price,
                stock=0,
                min_stock=rng.choice([3, 4, 5, 6, 8, 10]),
                price_code=code,
            )
            db.session.add(product)
            db.session.flush()
            simulate(product, user.id, suppliers, rng, start, now, popularity=rng.uniform(0.05, 0.55))
        db.session.commit()

        low = sum(1 for p in Product.query.all() if p.min_stock and p.stock <= p.min_stock)
        print(f"Productos: {len(models)} · movimientos: {StockMovement.query.count()} · "
              f"alertas abiertas: {StockAlert.query.filter_by(status='ABIERTA').count()} · "
              f"en o bajo el mínimo: {low}")


if __name__ == "__main__":
    main()
