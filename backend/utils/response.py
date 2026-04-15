from flask import jsonify


def success_response(message="Success", data=None, code=1, status_code=200):
    """
    Match Laravel's response format:
    {"code": 1, "message": "...", "data": {...}}
    """
    response = {
        "code": code,
        "message": message,
    }
    if data is not None:
        response["data"] = data
    return jsonify(response), status_code


def error_response(message="Error", data=None, code=0, status_code=400):
    """
    Match Laravel's error response format:
    {"code": 0, "message": "...", "data": null}
    """
    response = {
        "code": code,
        "message": message,
    }
    if data is not None:
        response["data"] = data
    return jsonify(response), status_code


def paginated_response(items, total, page, per_page, message="Success"):
    """
    Match Laravel's pagination format:
    {"code": 1, "message": "...", "data": {"current_page": 1, "data": [...], ...}}
    """
    import math
    return jsonify({
        "code": 1,
        "message": message,
        "data": {
            "current_page": page,
            "data": items,
            "per_page": per_page,
            "total": total,
            "last_page": math.ceil(total / per_page) if per_page > 0 else 1,
        }
    }), 200
