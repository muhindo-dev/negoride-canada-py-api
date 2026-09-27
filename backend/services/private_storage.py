"""Private object storage (spec §2.9, §10.1) — recordings, safety-report
attachments, and (reusable) driver documents / receipts.

    from backend.services import private_storage as PS
    PS.put('recordings/12/34/00001.m4a', data, 'audio/mp4')
    PS.get(key) -> bytes
    PS.delete(key)
    PS.signed_url(key, ttl_s=300, content_type=None, filename=None, actor_id=None) -> str

Backends
  s3     when S3_BUCKET_PRIVATE + S3_ACCESS_KEY + S3_SECRET_KEY are set
         (S3_ENDPOINT for S3-compatible providers, S3_REGION, S3_SSE=AES256|'' ).
         Objects are written with server-side encryption; signed_url() returns a
         short-lived presigned GET URL.
  local  otherwise: files under PRIVATE_STORAGE_DIR (default <repo>/private_storage,
         never web-served), encrypted at rest with Fernet (key: PRIVATE_STORAGE_KEY).
         signed_url() returns an HMAC-signed, expiring URL served by
         GET /api/private-files/<token> (backend/routes/recordings.py).

Nothing here is ever reachable through /uploads or /storage.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time

log = logging.getLogger('negoride.private_storage')

_KEY_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9/_.\-]{0,480}$')
_backend = None


class StorageError(Exception):
    pass


def _check_key(key):
    if not key or not _KEY_RE.match(key) or '..' in key or key.startswith('/'):
        raise StorageError(f'Invalid storage key: {key!r}')
    return key


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── local (Fernet-encrypted filesystem) ─────────────────────────────────────

class LocalBackend:
    name = 'local'

    def __init__(self, root=None, key=None):
        self.root = os.path.abspath(root or os.getenv('PRIVATE_STORAGE_DIR') or
                                    os.path.join(_repo_root(), 'private_storage'))
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        self._raw_key = self._load_key(key)
        from cryptography.fernet import Fernet
        self.fernet = Fernet(self._raw_key)

    def _load_key(self, key):
        key = key or os.getenv('PRIVATE_STORAGE_KEY', '').strip()
        if key:
            try:
                if len(base64.urlsafe_b64decode(key.encode())) == 32:
                    return key.encode()
            except Exception:
                pass
            # Any other secret string: derive a valid Fernet key from it.
            return base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        if os.getenv('FLASK_ENV', '').lower() == 'production':
            raise StorageError('PRIVATE_STORAGE_KEY must be set in production')
        path = os.path.join(self.root, '.dev_fernet_key')
        if os.path.exists(path):
            with open(path, 'rb') as fh:
                return fh.read().strip()
        from cryptography.fernet import Fernet
        k = Fernet.generate_key()
        with open(path, 'wb') as fh:
            fh.write(k)
        os.chmod(path, 0o600)
        log.warning('PRIVATE_STORAGE_KEY not set — generated a DEV key at %s. '
                    'Set PRIVATE_STORAGE_KEY in every non-dev environment.', path)
        return k

    def hmac_secret(self):
        return hashlib.sha256(b'negoride-signed-url:' + self._raw_key).digest()

    def _path(self, key):
        p = os.path.abspath(os.path.join(self.root, _check_key(key) + '.enc'))
        if not p.startswith(self.root + os.sep):
            raise StorageError('Invalid storage key')
        return p

    def put(self, key, data, content_type=None):
        p = self._path(key)
        os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
        tmp = p + '.tmp'
        with open(tmp, 'wb') as fh:
            fh.write(self.fernet.encrypt(bytes(data)))
        os.replace(tmp, p)
        return key

    def get(self, key):
        p = self._path(key)
        if not os.path.exists(p):
            raise StorageError('Object not found')
        with open(p, 'rb') as fh:
            return self.fernet.decrypt(fh.read())

    def exists(self, key):
        return os.path.exists(self._path(key))

    def delete(self, key):
        p = self._path(key)
        try:
            os.remove(p)
            return True
        except FileNotFoundError:
            return False

    def signed_url(self, key, ttl_s=300, content_type=None, filename=None, actor_id=None):
        _check_key(key)
        payload = {'k': key, 'e': int(time.time()) + int(ttl_s)}
        if content_type:
            payload['ct'] = content_type
        if filename:
            payload['fn'] = filename
        if actor_id:
            payload['u'] = int(actor_id)
        raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')
        sig = hmac.new(self.hmac_secret(), raw.encode(), hashlib.sha256).hexdigest()[:40]
        base = os.getenv('PUBLIC_API_BASE_URL', '').rstrip('/')
        return f'{base}/api/private-files/{raw}.{sig}'

    def verify_token(self, token):
        """Returns the payload dict for a valid, unexpired token, else None."""
        try:
            raw, sig = token.rsplit('.', 1)
        except ValueError:
            return None
        good = hmac.new(self.hmac_secret(), raw.encode(), hashlib.sha256).hexdigest()[:40]
        if not hmac.compare_digest(good, sig):
            return None
        try:
            payload = json.loads(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)))
        except Exception:
            return None
        if int(payload.get('e', 0)) < time.time():
            return None
        return payload


# ── S3-compatible ───────────────────────────────────────────────────────────

class S3Backend:
    name = 's3'

    def __init__(self):
        import boto3
        self.bucket = os.getenv('S3_BUCKET_PRIVATE')
        self.sse = os.getenv('S3_SSE', 'AES256').strip()
        self.client = boto3.client(
            's3', endpoint_url=os.getenv('S3_ENDPOINT') or None,
            aws_access_key_id=os.getenv('S3_ACCESS_KEY'), aws_secret_access_key=os.getenv('S3_SECRET_KEY'),
            region_name=os.getenv('S3_REGION') or 'us-east-1')

    def put(self, key, data, content_type=None):
        extra = {'ContentType': content_type or 'application/octet-stream'}
        if self.sse:
            extra['ServerSideEncryption'] = self.sse
        self.client.put_object(Bucket=self.bucket, Key=_check_key(key), Body=bytes(data), **extra)
        return key

    def get(self, key):
        try:
            return self.client.get_object(Bucket=self.bucket, Key=_check_key(key))['Body'].read()
        except Exception as exc:
            raise StorageError(f'Object not found: {exc}')

    def exists(self, key):
        try:
            self.client.head_object(Bucket=self.bucket, Key=_check_key(key))
            return True
        except Exception:
            return False

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=_check_key(key))
        return True

    def signed_url(self, key, ttl_s=300, content_type=None, filename=None, actor_id=None):
        params = {'Bucket': self.bucket, 'Key': _check_key(key)}
        if content_type:
            params['ResponseContentType'] = content_type
        if filename:
            params['ResponseContentDisposition'] = f'inline; filename="{filename}"'
        return self.client.generate_presigned_url('get_object', Params=params, ExpiresIn=int(ttl_s))

    def verify_token(self, token):
        return None


# ── module API ──────────────────────────────────────────────────────────────

def s3_configured():
    return all(os.getenv(k) for k in ('S3_BUCKET_PRIVATE', 'S3_ACCESS_KEY', 'S3_SECRET_KEY'))


def backend():
    global _backend
    if _backend is None:
        _backend = S3Backend() if s3_configured() else LocalBackend()
    return _backend


def configure(backend_obj=None, root=None, key=None):
    """Tests / tooling: swap the backend (e.g. LocalBackend(root=tmp))."""
    global _backend
    _backend = backend_obj or (LocalBackend(root=root, key=key) if (root or key) else None)
    return _backend


def put(key, data, content_type=None):
    return backend().put(key, data, content_type)


def get(key):
    return backend().get(key)


def exists(key):
    return backend().exists(key)


def delete(key):
    try:
        return backend().delete(key)
    except StorageError:
        return False


def signed_url(key, ttl_s=300, content_type=None, filename=None, actor_id=None):
    return backend().signed_url(key, ttl_s=ttl_s, content_type=content_type, filename=filename, actor_id=actor_id)


def verify_token(token):
    return backend().verify_token(token)


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()
