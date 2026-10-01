"""Selfie ↔ driver's licence face match (spec §14.1 step 5 "selfie for face match").

Advisory only: the result is stored on the selfie DriverDocument
(face_match_status / face_match_score / face_match_provider /
face_match_checked_at / face_match_detail) and shown to the reviewer in the
admin application detail. It NEVER approves or rejects anything by itself.

Provider selection
  AWS Rekognition CompareFaces  when AWS_REKOGNITION_REGION is set and AWS
                                credentials are available (AWS_ACCESS_KEY_ID +
                                AWS_SECRET_ACCESS_KEY, or the default boto3 chain
                                when AWS_REKOGNITION_USE_DEFAULT_CHAIN=1)
  none                          → status `manual_review` (reviewer compares by eye)

Statuses: pending | match | no_match | no_face | manual_review | error
`match` = similarity ≥ onboarding.face_match_threshold (0-100).
"""
import logging
import os
from datetime import datetime

from backend.models import db
from backend.models.identity import DriverDocument
from backend.services import settings_service as S
from backend.services.audit import audit

log = logging.getLogger('negoride.face_match')

COMPARABLE_MIME = ('image/jpeg', 'image/jpg', 'image/png')
_provider_override = None


class FaceMatchError(Exception):
    pass


class RekognitionProvider:
    name = 'aws_rekognition'

    def __init__(self, region):
        import boto3
        kwargs = {'region_name': region}
        if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
            kwargs.update(aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                          aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'))
        self.client = boto3.client('rekognition', **kwargs)

    def compare(self, source_bytes, target_bytes):
        """→ (similarity 0-100 or None when no face was found, detail)."""
        try:
            res = self.client.compare_faces(SourceImage={'Bytes': source_bytes}, TargetImage={'Bytes': target_bytes},
                                            SimilarityThreshold=0, QualityFilter='AUTO')
        except Exception as exc:   # botocore ClientError / InvalidParameterException (no face)
            msg = str(exc)
            if 'InvalidParameter' in msg or 'no face' in msg.lower():
                return None, 'No face detected in one of the images.'
            raise FaceMatchError(msg[:300])
        matches = res.get('FaceMatches') or []
        if not matches:
            return 0.0, f"No matching face ({len(res.get('UnmatchedFaces') or [])} unmatched)."
        best = max(float(m.get('Similarity') or 0) for m in matches)
        return round(best, 2), f'{len(matches)} matching face(s).'


def set_provider(provider):
    """Tests: inject a provider object with .name and .compare(src, tgt)."""
    global _provider_override
    _provider_override = provider


def get_provider():
    if _provider_override is not None:
        return _provider_override
    region = os.getenv('AWS_REKOGNITION_REGION', '').strip()
    if not region:
        return None
    has_keys = bool(os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'))
    if not has_keys and os.getenv('AWS_REKOGNITION_USE_DEFAULT_CHAIN') != '1':
        return None
    try:
        return RekognitionProvider(region)
    except Exception as exc:
        log.warning('Rekognition unavailable: %s', exc)
        return None


def _latest(application_id, doc_type):
    return (DriverDocument.query.filter(DriverDocument.application_id == application_id,
                                        DriverDocument.type == doc_type, DriverDocument.status != 'superseded')
            .order_by(DriverDocument.id.desc()).first())


def run_for_application(application_id):
    """Job: compare the latest selfie with the latest licence (front). Idempotent per selfie+licence pair."""
    selfie = _latest(application_id, 'selfie')
    licence = _latest(application_id, 'licence_front')
    if not selfie or not licence:
        return None
    meta = dict(selfie.meta or {})
    if meta.get('face_match_licence_id') == licence.id and selfie.face_match_status not in (None, 'pending', 'error'):
        return selfie.face_match_status
    provider = get_provider()
    score, detail, status = None, None, None
    if provider is None:
        status, detail = 'manual_review', 'No face-match provider configured — compare the photos manually.'
    elif (selfie.mime_type or '') not in COMPARABLE_MIME or (licence.mime_type or '') not in COMPARABLE_MIME:
        status, detail = 'manual_review', 'Automatic comparison needs JPEG/PNG photos — compare manually.'
    else:
        from backend.services import private_storage as PS
        try:
            score, detail = provider.compare(PS.get(selfie.file_path), PS.get(licence.file_path))
            if score is None:
                status = 'no_face'
            else:
                status = 'match' if score >= S.get_int('onboarding.face_match_threshold') else 'no_match'
        except Exception as exc:
            status, detail = 'error', f'Face match failed: {exc}'[:500]
            log.warning('face match failed for application %s: %s', application_id, exc)
    selfie.face_match_status = status
    selfie.face_match_score = score
    selfie.face_match_provider = getattr(provider, 'name', None) or 'none'
    selfie.face_match_checked_at = datetime.utcnow()
    selfie.face_match_detail = (detail or '')[:500] or None
    meta['face_match_licence_id'] = licence.id
    selfie.meta = meta
    audit('onboarding.face_match', None, 'driver_document', selfie.id,
          after={'status': status, 'score': float(score) if score is not None else None,
                 'provider': selfie.face_match_provider, 'licence_document_id': licence.id})
    db.session.commit()
    return status


def summary(application_id):
    """Admin payload: {status, score, provider, checked_at, detail, selfie_document_id, licence_document_id}."""
    selfie = _latest(application_id, 'selfie')
    if not selfie:
        return None
    return {'status': selfie.face_match_status or ('pending' if _latest(application_id, 'licence_front') else None),
            'score': float(selfie.face_match_score) if selfie.face_match_score is not None else None,
            'provider': selfie.face_match_provider,
            'checked_at': selfie.face_match_checked_at.strftime('%Y-%m-%dT%H:%M:%SZ') if selfie.face_match_checked_at else None,
            'detail': selfie.face_match_detail, 'selfie_document_id': selfie.id,
            'licence_document_id': (selfie.meta or {}).get('face_match_licence_id'),
            'threshold': S.get_int('onboarding.face_match_threshold'),
            'advisory_only': True}
