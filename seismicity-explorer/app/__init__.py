import os

from flask import Flask


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["DATABASE"] = {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "dbname": os.environ.get("PGDATABASE", "seismicity"),
        "user": os.environ.get("PGUSER", "seismicity"),
        "password": os.environ.get("PGPASSWORD", ""),
    }
    app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

    from .routes import api

    app.register_blueprint(api)
    return app
