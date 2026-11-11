"""WSGI entry point for production servers: ``gunicorn touchline_takes.wsgi:app``."""

import logging

from touchline_takes.web import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
