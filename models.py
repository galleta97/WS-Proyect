"""
Modelos de datos para el dashboard de pricing intelligence.

Reflejan la misma forma de entidades que encontramos al mapear la
plataforma de referencia (3Eye): Categorías, Marcas, Retailers,
Importadoras, Importaciones (aduana), Precios de "Web Homes" (scraping de
imágenes de home pages), Eventos de marketing, Features, y una tabla de
"price matrix" para la vista de Top Sales / ranking de ventas.
"""

from datetime import date, datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


# ---------------------------------------------------------------------------
# Usuarios (autenticación)
# ---------------------------------------------------------------------------

class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(200), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)


# ---------------------------------------------------------------------------
# Catálogos base
# ---------------------------------------------------------------------------

class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(120), nullable=False, unique=True)

    def to_dict(self):
        return {"id": self.id, "code": self.code}


class Retail(db.Model):
    __tablename__ = "retails"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(120), nullable=False, unique=True)
    color = db.Column(db.String(20), nullable=True)

    def to_dict(self):
        return {"id": self.id, "code": self.code, "color": self.color}


class Brand(db.Model):
    __tablename__ = "brands"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(160), nullable=False)

    category_ids = db.relationship(
        "Category", secondary="brand_categories", lazy="joined"
    )
    retail_ids = db.relationship(
        "Retail", secondary="brand_retails", lazy="joined"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "categoryIds": [c.id for c in self.category_ids],
            "retailIds": [r.id for r in self.retail_ids],
        }


brand_categories = db.Table(
    "brand_categories",
    db.Column("brand_id", db.Integer, db.ForeignKey("brands.id"), primary_key=True),
    db.Column("category_id", db.Integer, db.ForeignKey("categories.id"), primary_key=True),
)

brand_retails = db.Table(
    "brand_retails",
    db.Column("brand_id", db.Integer, db.ForeignKey("brands.id"), primary_key=True),
    db.Column("retail_id", db.Integer, db.ForeignKey("retails.id"), primary_key=True),
)


class Importer(db.Model):
    __tablename__ = "importers"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(200), nullable=False)

    def to_dict(self):
        return {"id": self.id, "code": self.code}


class Feature(db.Model):
    __tablename__ = "features"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "categoryIds": [self.category_id] if self.category_id else [],
        }


class MktEvent(db.Model):
    __tablename__ = "mkt_events"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(120), nullable=False)
    from_date = db.Column(db.Date, nullable=False)
    to_date = db.Column(db.Date, nullable=False)
    year = db.Column(db.Integer, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "fromDate": self.from_date.isoformat(),
            "toDate": self.to_date.isoformat(),
            "year": self.year,
        }


# ---------------------------------------------------------------------------
# Importaciones (aduana)
# ---------------------------------------------------------------------------

class ImportRecord(db.Model):
    __tablename__ = "import_records"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"), nullable=True)
    product_code = db.Column(db.String(120), nullable=False)
    importer_id = db.Column(db.Integer, db.ForeignKey("importers.id"), nullable=True)
    description = db.Column(db.Text, nullable=True)
    cost = db.Column(db.Numeric(12, 4), nullable=False, default=0)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    aduana_code = db.Column(db.String(60), nullable=True)
    feature1 = db.Column(db.String(40), nullable=True)
    feature2 = db.Column(db.String(80), nullable=True)
    origin = db.Column(db.String(120), nullable=True)

    category = db.relationship("Category")
    brand = db.relationship("Brand")
    importer = db.relationship("Importer")

    def to_dict(self):
        return {
            "date": self.date.isoformat(),
            "categoryId": self.category_id,
            "category": self.category.code if self.category else None,
            "brand": self.brand.code if self.brand else None,
            "productCode": self.product_code,
            "importer": self.importer.code if self.importer else None,
            "description": self.description,
            "cost": str(self.cost),
            "quantity": self.quantity,
            "amount": float(self.cost) * self.quantity,
            "aduanaCode": self.aduana_code,
            "feature1": self.feature1,
            "feature2": self.feature2,
            "origin": self.origin,
        }


# ---------------------------------------------------------------------------
# Web Homes (precios extraídos de imágenes del home de cada retailer)
# ---------------------------------------------------------------------------

class WebHome(db.Model):
    __tablename__ = "web_homes"
    id = db.Column(db.Integer, primary_key=True)
    country = db.Column(db.String(10), nullable=True)
    retail_id = db.Column(db.Integer, db.ForeignKey("retails.id"), nullable=False)
    url = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.Date, nullable=False, default=date.today)

    retail = db.relationship("Retail")

    def to_dict(self):
        return {
            "id": self.id,
            "country": self.country,
            "retailId": self.retail_id,
            "retail": self.retail.code if self.retail else None,
            "createdAt": self.created_at.isoformat(),
            "url": self.url,
        }


class WebHomePrice(db.Model):
    __tablename__ = "web_home_prices"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    retail_id = db.Column(db.Integer, db.ForeignKey("retails.id"), nullable=False)
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"), nullable=True)
    product = db.Column(db.String(200), nullable=False)
    actual = db.Column(db.Numeric(12, 2), nullable=True)
    offer = db.Column(db.Numeric(12, 2), nullable=True)
    normal = db.Column(db.Numeric(12, 2), nullable=True)
    discounts = db.Column(db.String(60), nullable=True)
    description = db.Column(db.Text, nullable=True)

    retail = db.relationship("Retail")
    brand = db.relationship("Brand")

    def to_dict(self):
        return {
            "date": self.date.isoformat(),
            "retail": self.retail.code if self.retail else None,
            "brand": self.brand.code if self.brand else None,
            "product": self.product,
            "actual": float(self.actual) if self.actual is not None else None,
            "offer": float(self.offer) if self.offer is not None else None,
            "normal": float(self.normal) if self.normal is not None else None,
            "discounts": self.discounts,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Price matrix / Top Sales (búsqueda de precios por tienda + ranking)
# ---------------------------------------------------------------------------

class PriceEntry(db.Model):
    """
    Una fila = 1 producto con su precio en una tienda específica y una fecha.
    La vista "Top Sales" filtra esto por has_sales_rank=True y ordena por
    sales_rank; la vista "Search" normal ignora el ranking y solo compara
    precios entre tiendas para un mismo producto.
    """
    __tablename__ = "price_entries"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    retail_id = db.Column(db.Integer, db.ForeignKey("retails.id"), nullable=False)
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"), nullable=True)
    product_code = db.Column(db.String(160), nullable=False)
    min_price = db.Column(db.Numeric(12, 2), nullable=False)
    has_sales_rank = db.Column(db.Boolean, nullable=False, default=False)
    sales_rank = db.Column(db.Integer, nullable=True)
    # Fase 4: disponibilidad de stock en esa tienda para ese SKU. Nullable
    # porque una fuente de datos que no reporte stock (ej. un scraper viejo
    # sin ese campo aún) no debe forzar un valor falso — None = "no se sabe".
    is_available = db.Column(db.Boolean, nullable=True)
    # Quién vende el producto DENTRO de esa tienda (en promart.pe, por ejemplo,
    # hay productos publicados por Plaza Vea, Carsa u otros vendedores).
    # Nullable: una fuente que no informe vendedor no debe forzar un valor.
    seller = db.Column(db.String(160), nullable=True)
    # Lo que muestra la web de ese listado (capturas reales):
    list_price = db.Column(db.Numeric(12, 2), nullable=True)   # precio de lista (tachado)
    card_price = db.Column(db.Numeric(12, 2), nullable=True)   # precio con tarjeta, si se logra leer
    listing_ref = db.Column(db.String(80), nullable=True)      # id del producto en esa tienda: varios listados pueden ser el mismo modelo
    url = db.Column(db.String(300), nullable=True)             # URL publica del producto en la tienda
    name = db.Column(db.String(300), nullable=True)            # nombre tal como lo publica la tienda
    ean = db.Column(db.String(20), nullable=True)              # solo si es un EAN-13 valido

    category = db.relationship("Category")
    retail = db.relationship("Retail")
    brand = db.relationship("Brand")

    def to_dict(self):
        return {
            "date": self.date.isoformat(),
            "category": self.category.code if self.category else None,
            "product": self.product_code,
            "brand": self.brand.code if self.brand else None,
            "retail": self.retail.code if self.retail else None,
            "minPrice": float(self.min_price),
            "salesRank": self.sales_rank,
            "isAvailable": self.is_available,
            "seller": self.seller,
            "url": self.url,
        }


# ---------------------------------------------------------------------------
# Alertas (Fase 3: cambios de precio; Fase 4 reutiliza esto para stock)
# ---------------------------------------------------------------------------

class PriceAlert(db.Model):
    """
    Un registro por cada cambio detectado (de precio o de stock) para un
    SKU en una tienda. `alert_type` distingue el tipo; `previous_value` y
    `new_value` se guardan como texto para poder reutilizar la misma tabla
    tanto para "1899.90" -> "1799.90" (precio) como para
    "disponible" -> "agotado" (stock, Fase 4).
    """
    __tablename__ = "price_alerts"
    id = db.Column(db.Integer, primary_key=True)
    product_code = db.Column(db.String(160), nullable=False)
    retail_id = db.Column(db.Integer, db.ForeignKey("retails.id"), nullable=False)
    alert_type = db.Column(db.String(30), nullable=False, default="price_change")
    previous_value = db.Column(db.String(60), nullable=True)
    new_value = db.Column(db.String(60), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    notified = db.Column(db.Boolean, nullable=False, default=False)
    notify_error = db.Column(db.String(300), nullable=True)

    retail = db.relationship("Retail")

    def to_dict(self):
        return {
            "id": self.id,
            "productCode": self.product_code,
            "retail": self.retail.code if self.retail else None,
            "alertType": self.alert_type,
            "previousValue": self.previous_value,
            "newValue": self.new_value,
            "createdAt": self.created_at.isoformat(),
            "notified": self.notified,
            "notifyError": self.notify_error,
        }
