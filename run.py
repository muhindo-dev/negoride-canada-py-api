#!/usr/bin/env python3
"""Entry point — run the Flask development server."""
import os
from dotenv import load_dotenv

load_dotenv()

from backend.app import app, socketio

if __name__ == '__main__':
    port = int(os.environ.get('SERVER_PORT', 5000))
    host = os.environ.get('SERVER_HOST', '0.0.0.0')

    # Auto-reload is a dev convenience and is independent of the debugger.
    use_reloader = os.environ.get('SERVER_RELOAD', '1') == '1'

    # The interactive Werkzeug debugger executes arbitrary code from the browser
    # console (protected only by a PIN) and dumps source + tracebacks. It must
    # NEVER be reachable over the network — only enable it on a loopback bind and
    # only when FLASK_DEBUG=1 is explicitly set.
    want_debugger = os.environ.get('FLASK_DEBUG', '0') == '1'
    is_loopback = host in ('127.0.0.1', 'localhost', '::1')
    enable_debugger = want_debugger and is_loopback

    socketio.run(
        app,
        host=host,
        port=port,
        debug=enable_debugger,
        use_reloader=use_reloader,
        use_debugger=enable_debugger,
        allow_unsafe_werkzeug=True,
    )
