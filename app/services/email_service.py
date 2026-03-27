"""
Service d'envoi d'emails via SMTP (smtplib standard + asyncio.to_thread).
Configure SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD dans .env
"""
import asyncio
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings


def _send_email_sync(to: str, subject: str, html_body: str) -> None:
    """Envoi synchrone — exécuté dans un thread séparé."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        print(f"\n{'='*60}")
        print(f"[EMAIL SIMULÉ] → {to}")
        print(f"Sujet  : {subject}")
        print(f"Corps  : {html_body[:300]}...")
        print(f"{'='*60}\n")
        return

    print(f"[EMAIL] Envoi vers {to} via {settings.SMTP_HOST}:{settings.SMTP_PORT}")
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = settings.SMTP_FROM
        msg["To"]      = to
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        context = ssl.create_default_context()
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.set_debuglevel(1)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            # Extraire juste l'adresse email du SMTP_FROM (sans le nom)
            from_addr = settings.SMTP_FROM
            if "<" in from_addr:
                from_addr = from_addr.split("<")[1].rstrip(">")
            server.sendmail(from_addr, to, msg.as_string())
        print(f"[EMAIL] ✅ Envoyé avec succès à {to}")
    except Exception as e:
        print(f"[EMAIL] ❌ ERREUR SMTP: {e}")
        raise


async def send_email(to: str, subject: str, html_body: str) -> None:
    """Envoi asynchrone (non-bloquant) d'un email."""
    await asyncio.to_thread(_send_email_sync, to, subject, html_body)


async def send_otp_email(to: str, code: str, admin_nom: str) -> None:
    """Email contenant le code OTP d'invitation."""
    html = f"""
<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;background:#f4f6f8;margin:0;padding:0;">
<table width="100%" cellpadding="0" cellspacing="0">
  <tr><td align="center" style="padding:40px 20px;">
    <table width="560" style="background:white;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
      <tr><td style="background:linear-gradient(135deg,#0F2235,#1A3F63);padding:32px;text-align:center;">
        <h1 style="color:white;font-size:24px;margin:0;font-family:'Georgia',serif;">EasyVoyage</h1>
        <p style="color:rgba(255,255,255,0.6);margin:8px 0 0;font-size:13px;">Plateforme de réservation</p>
      </td></tr>
      <tr><td style="padding:40px 48px;">
        <p style="color:#0F2235;font-size:16px;margin:0 0 12px;">Bonjour,</p>
        <p style="color:#4A5568;font-size:14px;line-height:1.6;margin:0 0 28px;">
          L'administrateur <strong>{admin_nom}</strong> souhaite vous inviter à rejoindre
          la plateforme <strong>EasyVoyage</strong> en tant que partenaire.
        </p>
        <p style="color:#4A5568;font-size:14px;margin:0 0 16px;">Votre code de vérification :</p>
        <div style="text-align:center;margin:28px 0;">
          <span style="display:inline-block;background:#EEF2F7;border:2px dashed #C4973A;
            border-radius:14px;padding:18px 48px;
            font-size:36px;font-weight:bold;color:#0F2235;letter-spacing:12px;">
            {code}
          </span>
        </div>
        <p style="color:#8A9BB0;font-size:13px;text-align:center;margin:0 0 28px;">
          Ce code expire dans <strong style="color:#C0392B;">15 minutes</strong>.
        </p>
        <p style="color:#4A5568;font-size:14px;line-height:1.6;margin:0;">
          Communiquez ce code à l'administrateur pour finaliser votre inscription.
        </p>
      </td></tr>
      <tr><td style="background:#F8FAFC;padding:20px 48px;text-align:center;">
        <p style="color:#B0BEC8;font-size:12px;margin:0;">
          Si vous n'attendiez pas cette invitation, ignorez cet email.
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>
"""
    await send_email(to, "Code de vérification — EasyVoyage", html)


async def send_welcome_partenaire_email(
    to: str, prenom: str, nom: str, password: str
) -> None:
    """Email de bienvenue avec mot de passe temporaire."""
    html = f"""
<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;background:#f4f6f8;margin:0;padding:0;">
<table width="100%" cellpadding="0" cellspacing="0">
  <tr><td align="center" style="padding:40px 20px;">
    <table width="560" style="background:white;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
      <tr><td style="background:linear-gradient(135deg,#0F2235,#1A3F63);padding:32px;text-align:center;">
        <h1 style="color:white;font-size:24px;margin:0;font-family:'Georgia',serif;">Bienvenue sur EasyVoyage</h1>
        <p style="color:rgba(255,255,255,0.6);margin:8px 0 0;font-size:13px;">Votre compte partenaire est activé</p>
      </td></tr>
      <tr><td style="padding:40px 48px;">
        <p style="color:#0F2235;font-size:16px;margin:0 0 12px;">Bonjour <strong>{prenom} {nom}</strong>,</p>
        <p style="color:#4A5568;font-size:14px;line-height:1.6;margin:0 0 28px;">
          Votre compte partenaire <strong>EasyVoyage</strong> a été créé avec succès.
          Voici vos identifiants de connexion :
        </p>
        <table width="100%" style="background:#F8FAFC;border-radius:12px;padding:0;margin-bottom:28px;">
          <tr>
            <td style="padding:16px 24px;border-bottom:1px solid #EEF2F7;">
              <span style="color:#8A9BB0;font-size:12px;font-weight:bold;text-transform:uppercase;letter-spacing:0.5px;">Email</span><br>
              <span style="color:#0F2235;font-size:15px;font-weight:600;">{to}</span>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 24px;">
              <span style="color:#8A9BB0;font-size:12px;font-weight:bold;text-transform:uppercase;letter-spacing:0.5px;">Mot de passe temporaire</span><br>
              <span style="display:inline-block;background:#EEF2F7;border:1.5px solid #C4973A;
                border-radius:8px;padding:8px 18px;margin-top:4px;
                font-size:18px;font-weight:bold;color:#0F2235;letter-spacing:4px;">
                {password}
              </span>
            </td>
          </tr>
        </table>
        <p style="color:#C0392B;font-size:13px;margin:0 0 24px;">
          ⚠️ Pensez à changer votre mot de passe après votre première connexion.
        </p>
        <div style="text-align:center;">
          <a href="http://localhost:3000" style="display:inline-block;
            background:linear-gradient(135deg,#0F2235,#1A3F63);
            color:white;text-decoration:none;padding:14px 36px;
            border-radius:10px;font-weight:bold;font-size:14px;">
            Accéder à la plateforme
          </a>
        </div>
      </td></tr>
      <tr><td style="background:#F8FAFC;padding:20px 48px;text-align:center;">
        <p style="color:#B0BEC8;font-size:12px;margin:0;">EasyVoyage — Votre partenaire de confiance</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>
"""
    await send_email(to, "Bienvenue sur EasyVoyage — Vos identifiants", html)