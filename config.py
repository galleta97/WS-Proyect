import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or ("sqlite:///" + os.path.join(BASE_DIR, "precios.db"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_AS_ASCII = False  # para que tildes/ñ salgan bien en las respuestas JSON

    # IMPORTANTE: esta clave firma las cookies de sesión (incluida la de
    # login). El valor de aquí es SOLO para desarrollo local. Antes de
    # desplegar esto en producción, cámbiala por un valor secreto real leído
    # de una variable de entorno, ej:
    #   SECRET_KEY = os.environ["SECRET_KEY"]
    # y nunca la subas a un repositorio.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me-before-deploy")
