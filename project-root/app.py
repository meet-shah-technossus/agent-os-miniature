from __future__ import annotations
from flask import Flask, render_template

from api import api_bp
from db import init_db


def create_app(test_config: dict | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping({
        "DATABASE_URL": "sqlite:///appointments.db"
    })
    if test_config:
        app.config.update(test_config)

    init_db(app)
    app.register_blueprint(api_bp)

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
