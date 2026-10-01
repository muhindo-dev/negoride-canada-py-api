import os
import socket

from flask import Flask, request, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_socketio import SocketIO

from backend.config import Config
from backend.models import db

# Initialize extensions
jwt = JWTManager()
socketio = SocketIO()


# (module, blueprint) pairs for v4 feature areas. Missing modules are skipped so
# a feature can be removed without editing this file.
V4_FEATURE_BLUEPRINTS = [
    ('backend.routes.safety', 'safety_bp'),
    ('backend.routes.admin_safety', 'admin_safety_bp'),
    ('backend.routes.tracking_share', 'tracking_share_bp'),
    ('backend.routes.recordings', 'recordings_bp'),
    ('backend.routes.verify', 'verify_bp'),
    ('backend.routes.legal', 'legal_bp'),
    ('backend.routes.onboarding', 'onboarding_bp'),
    ('backend.routes.account', 'account_bp'),
    ('backend.routes.support', 'support_bp'),
    ('backend.routes.admin_identity', 'admin_identity_bp'),
    ('backend.routes.receipts', 'receipts_bp'),
    ('backend.routes.admin_finance', 'admin_finance_bp'),
    ('backend.routes.ratings', 'ratings_bp'),
    ('backend.routes.rideshare_v4', 'rideshare_v4_bp'),
    ('backend.routes.carhire_v4', 'carhire_v4_bp'),
    ('backend.routes.admin_experience', 'admin_experience_bp'),
    ('backend.routes.docs', 'docs_bp'),
]


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Behind nginx: trust exactly TRUSTED_PROXY_COUNT (default 1) proxy hops, so
    # request.remote_addr is the real client IP (rate limits, audit) and a
    # client-supplied X-Forwarded-For can't spoof it. 0 = no proxy (direct).
    _proxies = int(os.getenv('TRUSTED_PROXY_COUNT', '1') or 0)
    if _proxies > 0:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=_proxies, x_proto=_proxies, x_host=0, x_prefix=0)

    # JSON: serialise Decimal as a NUMBER, not a string. Flask's default provider
    # renders Decimal via str() (e.g. "0.90"), which breaks mobile clients that do
    # numeric math / `.toStringAsFixed()` on money fields. Money columns are
    # Numeric(10,2) -> Decimal, so this makes every balance/amount a real number.
    from decimal import Decimal as _Decimal
    from flask.json.provider import DefaultJSONProvider

    class _NumberSafeJSONProvider(DefaultJSONProvider):
        @staticmethod
        def default(o):
            if isinstance(o, _Decimal):
                return float(o)
            return DefaultJSONProvider.default(o)

    app.json = _NumberSafeJSONProvider(app)

    # Guard: a LIVE Stripe key outside production means any test payment creates
    # a REAL charge. Warn loudly so it isn't discovered by an accidental charge.
    if (app.config.get('STRIPE_SECRET_KEY', '').startswith('sk_live_')
            and os.getenv('FLASK_ENV', '').lower() != 'production'):
        import sys
        print('\n⚠️  WARNING: a LIVE Stripe secret key (sk_live_…) is configured '
              'while FLASK_ENV is not "production". Real charges can occur — use '
              'a sk_test_… key for local/dev.\n', file=sys.stderr, flush=True)

    # Initialize extensions
    db.init_app(app)
    jwt.init_app(app)

    # CORS applies only to browser clients (the React admin SPA). The mobile app
    # is not subject to it, and auth here is header-based (no cookies), so there
    # is no CSRF vector. Still, allow production to restrict origins via env:
    #   CORS_ORIGINS="https://admin.example.com,https://foo.example.com"
    _cors_env = os.getenv('CORS_ORIGINS', '*').strip()
    cors_origins = '*' if _cors_env in ('', '*') else [o.strip() for o in _cors_env.split(',') if o.strip()]
    app.config['_CORS_ORIGINS'] = cors_origins
    CORS(app, resources={r"/api/*": {"origins": cors_origins}, r"/socket.io/*": {"origins": cors_origins}})

    # Initialize Socket.IO for real-time call signaling
    # With Redis available, Socket.IO uses it as a message queue so background
    # workers (RQ) can emit realtime events to connected clients.
    from backend import jobs as _jobs
    _mq = _jobs.redis_url() if (_jobs.mode() == 'rq') else None
    socketio.init_app(
        app,
        message_queue=_mq,
        cors_allowed_origins=cors_origins,
        async_mode='threading',  # Compatible with Flask debug mode
        ping_timeout=60,
        ping_interval=25,
        logger=True,
        engineio_logger=True,
        path='/socket.io',
    )

    # Ensure upload directory exists
    os.makedirs(app.config.get('UPLOAD_FOLDER', 'uploads'), exist_ok=True)

    # Register blueprints
    from backend.routes.auth import auth_bp
    from backend.routes.profile import profile_bp
    from backend.routes.trips import trips_bp
    from backend.routes.negotiations import negotiations_bp
    from backend.routes.bookings import bookings_bp
    from backend.routes.wallet import wallet_bp
    from backend.routes.payout_account import payout_account_bp
    from backend.routes.payout_requests import payout_requests_bp
    from backend.routes.chat import chat_bp
    from backend.routes.location import location_bp
    from backend.routes.resources import resources_bp
    from backend.routes.webhooks import webhooks_bp
    from backend.routes.admin import admin_bp
    from backend.routes.stream import stream_bp
    from backend.routes.calls import calls_bp
    from backend.routes.rides import rides_bp
    from backend.routes.notifications import notifications_bp
    from backend.routes.admin_v4 import admin_v4_bp
    from backend.routes.payment_pages import payment_pages_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(trips_bp)
    app.register_blueprint(negotiations_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(wallet_bp)
    app.register_blueprint(payout_account_bp)
    app.register_blueprint(payout_requests_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(location_bp)
    app.register_blueprint(resources_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(stream_bp)
    app.register_blueprint(calls_bp)
    app.register_blueprint(rides_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(admin_v4_bp)
    app.register_blueprint(payment_pages_bp)

    # v4 feature blueprints (registered when present)
    import importlib
    for _mod, _bp in V4_FEATURE_BLUEPRINTS:
        try:
            app.register_blueprint(getattr(importlib.import_module(_mod), _bp))
        except ModuleNotFoundError as _e:
            if _e.name != _mod:
                raise

    # Register Socket.IO call signaling events
    from backend.sockets.call_events import register_call_events
    register_call_events(socketio, app)

    # v4 realtime namespace (/rt): JWT-authenticated rooms user:/ride:/admin:
    from backend.sockets.realtime_events import register_realtime_events
    register_realtime_events(socketio, app)

    # Periodic scheduler inside the API process (single-box dev). Production
    # runs it in worker.py instead. Under the reloader only the child runs it.
    _reloading = os.getenv('SERVER_RELOAD', '1') == '1' and os.getenv('FLASK_ENV', '') != 'production'
    if os.getenv('RUN_SCHEDULER', '0') == '1' and (not _reloading or os.getenv('WERKZEUG_RUN_MAIN') == 'true'):
        from backend.jobs import scheduler as _scheduler
        _scheduler.start_in_background()

    # Loud warning when Redis is configured but unusable, or absent in production
    # (also listed by GET /api/admin/readiness).
    try:
        from backend.services.readiness import log_startup_warnings
        log_startup_warnings()
    except Exception:  # never block startup on a diagnostic
        pass

    from backend.utils.response import error_response

    @app.errorhandler(404)
    def handle_404(_error):
        if request.path.startswith('/api/'):
            return error_response("Endpoint not found.", status_code=404)
        return _error

    @app.errorhandler(405)
    def handle_405(_error):
        if request.path.startswith('/api/'):
            return error_response("Method not allowed for this endpoint.", status_code=405)
        return _error

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        """Never leak a stack trace / SQL to a client.

        API paths always get the standard {code, message} envelope; other paths
        keep Flask's default handling (SPA/static). HTTP errors keep their
        status code; unexpected errors become a clean 500 after rolling back any
        half-open transaction so the failure can't poison the shared session.
        """
        from werkzeug.exceptions import HTTPException
        from backend.models import db

        if isinstance(error, HTTPException):
            if request.path.startswith('/api/'):
                return error_response(error.description or error.name,
                                      status_code=error.code or 500)
            return error

        try:
            db.session.rollback()
        except Exception:
            pass
        app.logger.exception(
            'Unhandled exception on %s %s', request.method, request.path)
        return error_response('Internal server error.', status_code=500)

    # Serve uploaded files
    @app.route('/uploads/<path:filename>')
    def serve_upload(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    @app.route('/storage/<path:filename>')
    def serve_storage(filename):
        """Compatibility with Laravel's storage path"""
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # ── Serve React Admin Frontend ──
    admin_build = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend', 'build')

    @app.route('/')
    def serve_admin():
        if os.path.isfile(os.path.join(admin_build, 'index.html')):
            return send_from_directory(admin_build, 'index.html')
        return {'status': 'ok', 'service': 'NegoRide Canada API', 'version': '1.0',
                'note': 'Admin frontend not built yet. Run: cd frontend && npm run build'}

    @app.route('/assets/<path:filename>')
    def serve_admin_assets(filename):
        return send_from_directory(os.path.join(admin_build, 'assets'), filename)

    @app.route('/<path:path>')
    def serve_admin_spa(path):
        """SPA fallback — serve index.html for any non-API route"""
        if path.startswith('api/'):
            from flask import abort
            abort(404)
        file_path = os.path.join(admin_build, path)
        if os.path.isfile(file_path):
            return send_from_directory(admin_build, path)
        if os.path.isfile(os.path.join(admin_build, 'index.html')):
            return send_from_directory(admin_build, 'index.html')
        return {'status': 'ok', 'service': 'NegoRide Canada API', 'version': '1.0'}

    return app


app = create_app()


if __name__ == '__main__':
    # Get local IP address
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()

    port = Config.SERVER_PORT

    print('=' * 70)
    print('[*] NegoRide Canada API Starting...')
    print(f'   Backend API:     http://127.0.0.1:{port}/api')
    print(f'   Network access:  http://{local_ip}:{port}/api')
    print(f'   Socket.IO:       ws://{local_ip}:{port}/socket.io')
    print(f'   Database:        MySQL (negoride)')
    print('=' * 70)

    socketio.run(
        app,
        host=Config.SERVER_HOST,
        port=port,
        debug=os.getenv('FLASK_DEBUG', 'true').lower() == 'true',
        allow_unsafe_werkzeug=True,
    )
