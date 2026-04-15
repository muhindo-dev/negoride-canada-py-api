#!/usr/bin/env python3
"""WSGI entry point for production (Gunicorn with eventlet)."""
import os
from dotenv import load_dotenv

load_dotenv()

from backend.app import app, socketio

# Gunicorn needs this
application = app
