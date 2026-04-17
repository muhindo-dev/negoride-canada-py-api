"""
Email Service — NegoRide Canada
Uses Python's built-in smtplib so no extra pip dependency is required.
If MAIL_USERNAME is not configured, emails are printed to stdout (dev mode).
"""
import smtplib
import ssl
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import current_app

logger = logging.getLogger(__name__)


def _send(to_address: str, subject: str, html_body: str) -> bool:
    """Internal helper that delivers one email. Returns True on success."""
    username = current_app.config.get('MAIL_USERNAME', '')
    password = current_app.config.get('MAIL_PASSWORD', '')
    server = current_app.config.get('MAIL_SERVER', 'smtp.gmail.com')
    port = current_app.config.get('MAIL_PORT', 587)
    use_tls = current_app.config.get('MAIL_USE_TLS', True)
    use_ssl = current_app.config.get('MAIL_USE_SSL', False)
    from_name = current_app.config.get('MAIL_FROM_NAME', 'NegoRide Canada')
    from_addr = current_app.config.get('MAIL_FROM_ADDRESS', username)

    if not username or not password:
        # Dev fallback — print to console so the app still works without SMTP
        logger.warning('[EmailService] SMTP not configured. Printing email to console.')
        print(f'\n{"="*60}')
        print(f'TO: {to_address}')
        print(f'SUBJECT: {subject}')
        print(html_body)
        print('=' * 60 + '\n')
        return True

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f'{from_name} <{from_addr}>'
    msg['To'] = to_address
    msg.attach(MIMEText(html_body, 'html'))

    try:
        context = ssl.create_default_context()
        if use_ssl:
            with smtplib.SMTP_SSL(server, port, context=context) as smtp:
                smtp.login(username, password)
                smtp.sendmail(from_addr, to_address, msg.as_string())
        else:
            with smtplib.SMTP(server, port) as smtp:
                if use_tls:
                    smtp.starttls(context=context)
                smtp.login(username, password)
                smtp.sendmail(from_addr, to_address, msg.as_string())
        return True
    except Exception as exc:
        logger.error(f'[EmailService] Failed to send email to {to_address}: {exc}')
        return False


def send_verification_email(to_address: str, name: str, token: str) -> bool:
    """Send an account verification email with a clickable link."""
    app_url = current_app.config.get('APP_URL', 'http://localhost:5001')
    app_name = current_app.config.get('APP_NAME', 'NegoRide Canada')
    verify_url = f'{app_url}/api/email/verify/{token}'

    subject = f'Verify your {app_name} account'
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px">
      <h2 style="color:#1a1a2e">Welcome to {app_name}!</h2>
      <p>Hi {name},</p>
      <p>Thank you for creating an account. Please verify your email address by clicking the button below.</p>
      <p style="text-align:center;margin:32px 0">
        <a href="{verify_url}"
           style="background:#f6b93b;color:#1a1a2e;padding:14px 28px;border-radius:8px;
                  text-decoration:none;font-weight:bold;font-size:16px">
          Verify My Email
        </a>
      </p>
      <p style="color:#666;font-size:13px">
        Or copy this link into your browser:<br>
        <a href="{verify_url}" style="color:#3273dc">{verify_url}</a>
      </p>
      <p style="color:#666;font-size:13px">
        This link expires in <strong>24 hours</strong>.
        If you did not create this account, you can safely ignore this email.
      </p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="color:#aaa;font-size:12px;text-align:center">&copy; {app_name}</p>
    </div>
    """
    return _send(to_address, subject, html)


def send_password_reset_email(to_address: str, name: str, token: str) -> bool:
    """Send a password reset email."""
    app_url = current_app.config.get('APP_URL', 'http://localhost:5001')
    app_name = current_app.config.get('APP_NAME', 'NegoRide Canada')
    # The mobile app handles the deep link; we pass the raw token so the app can
    # open the ResetPasswordScreen directly via a custom URL scheme.
    reset_url = f'negoride://reset-password?token={token}'
    # Also include a web fallback in case the app is not installed
    web_url = f'{app_url}/api/auth/reset-password-page?token={token}'

    subject = f'Reset your {app_name} password'
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px">
      <h2 style="color:#1a1a2e">Password Reset Request</h2>
      <p>Hi {name},</p>
      <p>We received a request to reset your {app_name} account password.
         Click the button below to choose a new password.</p>
      <p style="text-align:center;margin:32px 0">
        <a href="{web_url}"
           style="background:#f6b93b;color:#1a1a2e;padding:14px 28px;border-radius:8px;
                  text-decoration:none;font-weight:bold;font-size:16px">
          Reset My Password
        </a>
      </p>
      <p style="color:#666;font-size:13px">
        Your reset code (enter in the app if needed): <strong>{token[:8].upper()}</strong>
      </p>
      <p style="color:#666;font-size:13px">
        This link expires in <strong>1 hour</strong>.
        If you did not request a password reset, please ignore this email.
        Your password will not change.
      </p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="color:#aaa;font-size:12px;text-align:center">&copy; {app_name}</p>
    </div>
    """
    return _send(to_address, subject, html)
