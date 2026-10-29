from flask import Flask
from flask_login import current_user
from dotenv import load_dotenv

load_dotenv()  # lee .env si existe, para SMTP_*, SLACK_WEBHOOK_URL, etc.

from config import Config
from extensions import db, login_manager


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Inicia sesión para continuar."
    login_manager.login_message_category = "error"

    @login_manager.user_loader
    def load_user(user_id):
        from models import User
        return db.session.get(User, int(user_id))

    from routes.api import api_bp
    from routes.views import views_bp
    from routes.auth import auth_bp
    from routes.inventory_api import inventory_api_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(inventory_api_bp)

    @app.context_processor
    def inject_user():
        return {
            "app_name": "Vigía",
            "current_user": current_user,
        }

    return app


app = create_app()

if __name__ == "__main__":
    import os
    # Con el reloader de debug, Flask ejecuta este archivo dos veces: el
    # proceso "vigía" externo (antes de que exista el servidor real) y el
    # proceso hijo que sí sirve peticiones. WERKZEUG_RUN_MAIN solo está
    # presente en ese proceso hijo — es el único chequeo confiable aquí.
    # (Ojo: `app.debug` todavía es False en este punto porque recién se
    # activa dentro de app.run(debug=True) más abajo, así que NO sirve
    # como condición para distinguir el proceso externo del hijo.)
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        from price_updater import start_price_watcher
        start_price_watcher(app)

    app.run(debug=True, port=5000)
