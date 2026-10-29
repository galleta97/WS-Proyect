from flask import Blueprint, render_template
from flask_login import login_required

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def landing():
    return render_template("landing.html")


@views_bp.route("/top")
@login_required
def top():
    return render_template("top.html", active="top")


@views_bp.route("/imports")
@login_required
def imports_page():
    return render_template("imports.html", active="imports")


@views_bp.route("/web-homes")
@login_required
def web_homes_page():
    return render_template("web_homes.html", active="web-homes")


@views_bp.route("/alerts")
@login_required
def alerts_page():
    return render_template("alerts.html", active="alerts")


@views_bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", active="dashboard")


@views_bp.route("/inventory")
@login_required
def inventory_page():
    return render_template("inventory.html", active="inventory")
