"""Customer / driver receipts and statements API (spec §13).

    GET /api/rides/{type}/{id}/receipt        JSON totals + number (ride parties only)
    GET /api/rides/{type}/{id}/receipt.pdf    the private PDF (ride parties only)
    GET /api/receipts?page=&per_page=         my receipts (as rider), newest first
    GET /api/receipts/{id}/credit-notes/{cn}.pdf   a credit note PDF (the rider)
    GET /api/receipts/tips/{id}.pdf           a tip receipt PDF (the rider)
    GET /api/brand/logo.png                   public email logo
    GET /api/driver/statements                my weekly earnings statements (driver)
    GET /api/driver/statements/{id}.pdf       statement PDF (owner only)
"""
from flask import Blueprint, Response, request

from backend.models import db
from backend.models.money import CreditNote, Receipt
from backend.models.statements import DriverStatement
from backend.services import receipts as RC
from backend.services import rides as R
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import error_response, paginated_response, success_response

receipts_bp = Blueprint('receipts', __name__)


def _page():
    page = max(1, request.args.get('page', 1, type=int))
    per = min(100, max(1, request.args.get('per_page', 20, type=int)))
    return page, per


def _pdf(blob, filename):
    inline = request.args.get('download') not in ('1', 'true')
    return Response(blob, mimetype='application/pdf', headers={
        'Content-Disposition': f'{"inline" if inline else "attachment"}; filename="{filename}"',
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
    })


def _party(user, ride_type, ride_id):
    """(rt, role) for the rider/driver of the ride; raises for others."""
    rt = R.normalize_type(ride_type)
    ride = R.load(rt, ride_id)
    uid = int(user.id)
    if R.driver_id(rt, ride) == uid:
        return rt, 'driver'
    if uid in R.customer_ids(rt, ride):
        return rt, 'customer'
    return rt, None


def _receipt_for(user, ride_type, ride_id):
    try:
        rt, role = _party(user, ride_type, ride_id)
    except R.RideNotFound as e:
        return None, None, error_response(str(e), data={'error_code': 'not_found'}, status_code=404)
    if role is None:
        return None, None, error_response('You are not part of this ride.', data={'error_code': 'forbidden'},
                                          status_code=403)
    receipt = RC.find_receipt(rt, ride_id)
    if receipt is None:
        return None, role, error_response('The receipt is not ready yet. It is emailed within a minute of the trip '
                                          'ending.', data={'error_code': 'receipt_not_ready'}, status_code=404)
    return receipt, role, None


@receipts_bp.route('/api/rides/<ride_type>/<int:ride_id>/receipt', methods=['GET'])
@jwt_required_with_user
def ride_receipt(user, ride_type, ride_id):
    receipt, role, err = _receipt_for(user, ride_type, ride_id)
    if err:
        return err
    return success_response('Receipt', RC.receipt_payload(receipt, viewer=role))


@receipts_bp.route('/api/rides/<ride_type>/<int:ride_id>/receipt.pdf', methods=['GET'])
@jwt_required_with_user
def ride_receipt_pdf(user, ride_type, ride_id):
    receipt, role, err = _receipt_for(user, ride_type, ride_id)
    if err:
        return err
    if role == 'driver':   # driver copy: rider first name only, no payment method
        return _pdf(RC.render_receipt_pdf(receipt, viewer='driver'), f'NegoRide-receipt-{receipt.number}-driver.pdf')
    return _pdf(RC.ensure_pdf(receipt), f'NegoRide-receipt-{receipt.number}.pdf')


@receipts_bp.route('/api/receipts/tips/<int:tip_receipt_id>.pdf', methods=['GET'])
@jwt_required_with_user
def tip_receipt_pdf(user, tip_receipt_id):
    from backend.models.money import TipReceipt
    tr = db.session.get(TipReceipt, tip_receipt_id)
    if tr is None:
        return error_response('Tip receipt not found', data={'error_code': 'not_found'}, status_code=404)
    if int(tr.customer_id) != int(user.id):
        return error_response('Forbidden', data={'error_code': 'forbidden'}, status_code=403)
    return _pdf(RC.ensure_tip_pdf(tr), f'NegoRide-tip-{tr.number}.pdf')


@receipts_bp.route('/api/brand/logo.png', methods=['GET'])
def brand_logo():
    """Public email logo (EMAIL_LOGO_URL overrides it)."""
    import os
    from flask import send_file
    path = os.path.join(RC.BACKEND_DIR, 'static', 'brand', 'logo.png')
    resp = send_file(path, mimetype='image/png', max_age=86400)
    return resp


@receipts_bp.route('/api/receipts', methods=['GET'])
@jwt_required_with_user
def my_receipts(user):
    page, per = _page()
    q = Receipt.query.filter(Receipt.customer_id == user.id)
    total = q.count()
    rows = q.order_by(Receipt.issued_at.desc(), Receipt.id.desc()).offset((page - 1) * per).limit(per).all()
    return paginated_response([RC.receipt_payload(r, viewer='customer') for r in rows], total, page, per,
                              message='Receipts')


@receipts_bp.route('/api/receipts/<int:receipt_id>/credit-notes/<int:cn_id>.pdf', methods=['GET'])
@jwt_required_with_user
def credit_note_pdf(user, receipt_id, cn_id):
    cn = db.session.get(CreditNote, cn_id)
    if cn is None or cn.receipt_id != receipt_id:
        return error_response('Credit note not found', data={'error_code': 'not_found'}, status_code=404)
    if int(cn.customer_id) != int(user.id):
        return error_response('Forbidden', data={'error_code': 'forbidden'}, status_code=403)
    return _pdf(RC.ensure_credit_note_pdf(cn), f'NegoRide-credit-note-{cn.number}.pdf')


def _statement_dict(st):
    d = st.to_dict(exclude=('totals',))
    d['totals'] = st.totals
    d['pdf_url'] = f'/api/driver/statements/{st.id}.pdf'
    return d


@receipts_bp.route('/api/driver/statements', methods=['GET'])
@jwt_required_with_user
def my_statements(user):
    page, per = _page()
    q = DriverStatement.query.filter(DriverStatement.driver_id == user.id)
    total = q.count()
    rows = q.order_by(DriverStatement.period_start.desc()).offset((page - 1) * per).limit(per).all()
    return paginated_response([_statement_dict(s) for s in rows], total, page, per, message='Statements')


@receipts_bp.route('/api/driver/statements/<int:statement_id>.pdf', methods=['GET'])
@jwt_required_with_user
def my_statement_pdf(user, statement_id):
    from backend.services import receipt_jobs
    st = db.session.get(DriverStatement, statement_id)
    if st is None:
        return error_response('Statement not found', data={'error_code': 'not_found'}, status_code=404)
    if int(st.driver_id) != int(user.id):
        return error_response('Forbidden', data={'error_code': 'forbidden'}, status_code=403)
    return _pdf(receipt_jobs.ensure_statement_pdf(st), f'NegoRide-statement-{st.number}.pdf')
