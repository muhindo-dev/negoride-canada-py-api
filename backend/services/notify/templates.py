"""Email templates (spec §13.1): Jinja2, responsive table layout, dark-mode
safe, always paired with a plain-text part. Templates live in
backend/templates/email/<name>.html (+ optional <name>.txt)."""
import os

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'templates', 'email')
_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(['html']))


def brand():
    from backend.services import settings_service as S
    base = (os.getenv('PUBLIC_WEB_BASE_URL') or S.get('company.website') or 'https://negoride.ca').rstrip('/')
    return {
        'brand_name': 'NegoRide Canada',
        'brand_color': '#EF9B11',
        'ink': '#111827',
        'web_base': base,
        'support_email': S.get('safety.support_email'),
        'support_phone': S.get('safety.support_phone'),
        'company_legal_name': S.get('company.legal_name'),
        'company_address': S.get('company.address'),
        'logo_url': os.getenv('EMAIL_LOGO_URL', f'{base}/logo.png'),
    }


def render(name, context):
    """Returns (html, text)."""
    ctx = {**brand(), **context}
    html = _env.get_template(f'{name}.html').render(**ctx)
    txt_path = os.path.join(TEMPLATE_DIR, f'{name}.txt')
    text = _env.get_template(f'{name}.txt').render(**ctx) if os.path.exists(txt_path) else None
    return html, text


def render_email(name, n, user):
    """Notification → (subject, html, text)."""
    first = (user.first_name or (user.name or '').split(' ')[0] or 'there').strip()
    data = n.data or {}
    cta_url = None
    if n.deep_link:
        cta_url = f"{brand()['web_base']}/open?link={n.deep_link}"
    html, text = render(name, {
        'title': n.title, 'body': n.body, 'first_name': first, 'data': data,
        'cta_label': data.get('cta_label') or 'Open NegoRide', 'cta_url': data.get('cta_url') or cta_url,
        'preheader': n.body,
    })
    return n.title, html, text
