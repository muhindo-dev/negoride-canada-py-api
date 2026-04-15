#!/usr/bin/env python3
"""Entry point — run the Flask development server."""
import os
from dotenv import load_dotenv

load_dotenv()

from backend.app import app, socketio

if __name__ == '__main__':
    port = int(os.environ.get('SERVER_PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
