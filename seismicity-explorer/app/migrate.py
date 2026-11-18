from . import create_app
from .db import migrate


application = create_app()
with application.app_context():
    migrate()
