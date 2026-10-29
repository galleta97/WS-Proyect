"""
Endpoints JSON del dashboard y del módulo de inventario.

Todos exigen sesión iniciada. El registro de movimientos solo acepta JSON,
así un formulario de otro sitio no puede enviarlo con la cookie del usuario.
"""

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import or_

from extensions import db
from inventory import InventoryError, dashboard_summary, register_movement, stock_status
from models import Product, StockAlert, StockMovement, Supplier

inventory_api_bp = Blueprint("inventory_api", __name__, url_prefix="/api")


def _reference_retail():
    from routes.api import REFERENCE_RETAIL_CODE
    return REFERENCE_RETAIL_CODE


@inventory_api_bp.route("/dashboard/summary")
@login_required
def summary():
    return jsonify(dashboard_summary(_reference_retail()))


@inventory_api_bp.route("/inventory/products")
@login_required
def products():
    q = Product.query.filter_by(active=True)
    term = request.args.get("q", "").strip()
    if term:
        like = f"%{term}%"
        q = q.filter(or_(Product.code.ilike(like), Product.name.ilike(like)))
    items = []
    for p in q.order_by(Product.code).limit(500).all():
        d = p.to_dict()
        d["status"] = stock_status(p)
        items.append(d)
    return jsonify(items)


@inventory_api_bp.route("/inventory/suppliers")
@login_required
def suppliers():
    rows = Supplier.query.filter_by(active=True).order_by(Supplier.business_name).all()
    return jsonify([s.to_dict() for s in rows])


@inventory_api_bp.route("/inventory/products/<int:product_id>/kardex")
@login_required
def kardex(product_id):
    product = db.session.get(Product, product_id)
    if product is None:
        return jsonify({"error": "Producto no encontrado."}), 404
    moves = (StockMovement.query.filter_by(product_id=product_id)
             .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
             .limit(200).all())
    alert = StockAlert.query.filter_by(product_id=product_id, status="ABIERTA").first()
    data = product.to_dict()
    data["status"] = stock_status(product)
    data["openAlert"] = alert.to_dict() if alert else None
    return jsonify({"product": data, "movements": [m.to_dict() for m in moves]})


@inventory_api_bp.route("/inventory/movements", methods=["POST"])
@login_required
def create_movement():
    if not request.is_json:
        return jsonify({"error": "Se esperaba JSON."}), 415
    body = request.get_json(silent=True) or {}
    try:
        movement, alert = register_movement(
            product_id=body.get("productId"),
            movement_type=body.get("type"),
            quantity=body.get("quantity"),
            user_id=current_user.id,
            supplier_id=body.get("supplierId"),
            reason=body.get("reason"),
        )
    except InventoryError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    product = movement.product
    data = product.to_dict()
    data["status"] = stock_status(product)
    return jsonify({
        "movement": movement.to_dict(),
        "product": data,
        "alertOpened": alert.to_dict() if alert else None,
    }), 201
