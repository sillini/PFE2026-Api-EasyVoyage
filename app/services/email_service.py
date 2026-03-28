"""
Service d'envoi d'emails via SMTP (smtplib standard + asyncio.to_thread).
Configure SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD dans .env
"""
import asyncio
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from email.mime.base      import MIMEBase
from email                import encoders

from app.core.config import settings


# ══════════════════════════════════════════════════════════
#  ENVOI EMAIL SIMPLE (texte / HTML)
# ══════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════
#  OTP INVITATION PARTENAIRE
# ══════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════
#  BIENVENUE PARTENAIRE
# ══════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════
#  VOUCHER PDF PAR EMAIL — VISITEUR
# ══════════════════════════════════════════════════════════

def _send_voucher_sync(
    to:           str,
    subject:      str,
    html_body:    str,
    pdf_bytes:    bytes,
    pdf_filename: str,
) -> None:
    """Envoi synchrone d'un email avec pièce jointe PDF."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        print(f"\n{'='*60}")
        print(f"[EMAIL VOUCHER SIMULÉ] → {to}")
        print(f"Sujet    : {subject}")
        print(f"PDF      : {pdf_filename} ({len(pdf_bytes)} bytes)")
        print(f"{'='*60}\n")
        return

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"]    = settings.SMTP_FROM
        msg["To"]      = to

        # Corps HTML
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # Pièce jointe PDF
        part = MIMEBase("application", "pdf")
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{pdf_filename}"',
        )
        msg.attach(part)

        context = ssl.create_default_context()
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            from_addr = settings.SMTP_FROM
            if "<" in from_addr:
                from_addr = from_addr.split("<")[1].rstrip(">")
            server.sendmail(from_addr, to, msg.as_string())
        print(f"[EMAIL VOUCHER] ✅ Envoyé à {to} — PDF : {pdf_filename}")
    except Exception as e:
        print(f"[EMAIL VOUCHER] ❌ ERREUR SMTP: {e}")
        raise


async def send_voucher_email(
    to:             str,
    prenom:         str,
    nom:            str,
    numero_voucher: str,
    hotel_nom:      str,
    hotel_ville:    str,
    chambre_nom:    str,
    date_debut:     str,
    date_fin:       str,
    nb_nuits:       int,
    nb_adultes:     int,
    nb_enfants:     int,
    montant:        float,
    methode:        str,
    pdf_bytes:      bytes,
) -> None:
    """
    Envoie le voucher PDF par email au visiteur après confirmation du paiement.
    Ne lève jamais d'exception — si l'envoi échoue, on log et on continue.
    La réservation est déjà enregistrée en base avant l'appel.
    """
    pdf_filename = f"voucher-{numero_voucher}.pdf"
    subject      = f"✈ Confirmation de réservation — {numero_voucher}"

    methode_label = {
        "CARTE_BANCAIRE": "Carte bancaire",
        "VIREMENT":       "Virement bancaire",
        "ESPECES":        "Espèces",
        "PAYPAL":         "PayPal",
        "CHEQUE":         "Chèque",
    }.get(methode, methode.replace("_", " ").title())

    enfants_ligne = (
        f"<tr style='background:#FAFBFC;'>"
        f"<td style='color:#8A9BB0;font-size:13px;padding:10px 18px;border-bottom:1px solid #F0F4F8;'>Enfants</td>"
        f"<td style='font-size:13px;font-weight:600;color:#0F2235;text-align:right;padding:10px 18px;border-bottom:1px solid #F0F4F8;'>"
        f"{nb_enfants}</td></tr>"
        if nb_enfants > 0 else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F4F6F8;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F6F8;">
  <tr><td align="center" style="padding:40px 20px;">
    <table width="560" cellpadding="0" cellspacing="0"
      style="background:#FFFFFF;border-radius:16px;overflow:hidden;
             box-shadow:0 4px 24px rgba(0,0,0,0.08);max-width:560px;width:100%;">

      <!-- En-tête -->
      <tr><td style="background:linear-gradient(135deg,#0F2235 0%,#1A3F63 100%);
                     padding:28px 44px;text-align:center;">
        <h1 style="color:#FFFFFF;font-size:24px;margin:0;font-family:Georgia,serif;
                   font-weight:700;letter-spacing:1px;">EasyVoyage</h1>
        <p style="color:rgba(255,255,255,0.55);margin:6px 0 0;font-size:12px;
                  text-transform:uppercase;letter-spacing:1px;">Confirmation de réservation</p>
      </td></tr>

      <!-- Bandeau succès -->
      <tr><td style="background:#F0FAF4;padding:20px 44px;text-align:center;
                     border-bottom:2px solid #27AE60;">
        <p style="margin:0;font-size:15px;color:#1D8A45;font-weight:700;">
          ✅ Paiement confirmé — Réservation validée
        </p>
      </td></tr>

      <!-- Corps -->
      <tr><td style="padding:32px 44px;">
        <p style="color:#0F2235;font-size:15px;margin:0 0 6px;font-weight:600;">
          Bonjour {prenom} {nom},
        </p>
        <p style="color:#4A5568;font-size:14px;line-height:1.7;margin:0 0 28px;">
          Votre réservation a bien été enregistrée. Votre <strong>voucher PDF</strong>
          est joint à cet email. Présentez-le à votre arrivée à l'hôtel.
        </p>

        <!-- N° Voucher mis en avant -->
        <div style="text-align:center;margin:0 0 28px;">
          <div style="display:inline-block;background:#F8FAFC;border:2px dashed #C4973A;
                      border-radius:12px;padding:14px 36px;">
            <p style="margin:0 0 4px;font-size:11px;color:#8A9BB0;text-transform:uppercase;
                      letter-spacing:0.8px;">N° Voucher</p>
            <p style="margin:0;font-size:22px;font-weight:700;color:#0F2235;
                      letter-spacing:3px;font-family:'Courier New',monospace;">
              {numero_voucher}
            </p>
          </div>
        </div>

        <!-- Détails réservation -->
        <table width="100%" cellpadding="0" cellspacing="0"
          style="border-radius:12px;overflow:hidden;border:1px solid #E8EDF5;">
          <tr><td colspan="2" style="background:#F8FAFC;padding:12px 18px;
                  border-bottom:1px solid #E8EDF5;">
            <p style="margin:0;font-size:12px;font-weight:700;color:#0F2235;
                      text-transform:uppercase;letter-spacing:0.6px;">
              🏨 Détails de la réservation
            </p>
          </td></tr>
          <tr>
            <td style="color:#8A9BB0;font-size:13px;padding:10px 18px;border-bottom:1px solid #F0F4F8;">Hôtel</td>
            <td style="font-size:13px;font-weight:700;color:#0F2235;text-align:right;padding:10px 18px;border-bottom:1px solid #F0F4F8;">{hotel_nom}</td>
          </tr>
          <tr style="background:#FAFBFC;">
            <td style="color:#8A9BB0;font-size:13px;padding:10px 18px;border-bottom:1px solid #F0F4F8;">Ville</td>
            <td style="font-size:13px;font-weight:600;color:#0F2235;text-align:right;padding:10px 18px;border-bottom:1px solid #F0F4F8;">{hotel_ville}</td>
          </tr>
          <tr>
            <td style="color:#8A9BB0;font-size:13px;padding:10px 18px;border-bottom:1px solid #F0F4F8;">Chambre</td>
            <td style="font-size:13px;font-weight:600;color:#0F2235;text-align:right;padding:10px 18px;border-bottom:1px solid #F0F4F8;">{chambre_nom}</td>
          </tr>
          <tr style="background:#FAFBFC;">
            <td style="color:#8A9BB0;font-size:13px;padding:10px 18px;border-bottom:1px solid #F0F4F8;">Arrivée</td>
            <td style="font-size:13px;font-weight:600;color:#0F2235;text-align:right;padding:10px 18px;border-bottom:1px solid #F0F4F8;">{date_debut}</td>
          </tr>
          <tr>
            <td style="color:#8A9BB0;font-size:13px;padding:10px 18px;border-bottom:1px solid #F0F4F8;">Départ</td>
            <td style="font-size:13px;font-weight:600;color:#0F2235;text-align:right;padding:10px 18px;border-bottom:1px solid #F0F4F8;">{date_fin}</td>
          </tr>
          <tr style="background:#FAFBFC;">
            <td style="color:#8A9BB0;font-size:13px;padding:10px 18px;border-bottom:1px solid #F0F4F8;">Durée</td>
            <td style="font-size:13px;font-weight:600;color:#0F2235;text-align:right;padding:10px 18px;border-bottom:1px solid #F0F4F8;">{nb_nuits} nuit{'s' if nb_nuits > 1 else ''}</td>
          </tr>
          <tr>
            <td style="color:#8A9BB0;font-size:13px;padding:10px 18px;border-bottom:1px solid #F0F4F8;">Adultes</td>
            <td style="font-size:13px;font-weight:600;color:#0F2235;text-align:right;padding:10px 18px;border-bottom:1px solid #F0F4F8;">{nb_adultes}</td>
          </tr>
          {enfants_ligne}
          <tr style="background:#FAFBFC;">
            <td style="color:#8A9BB0;font-size:13px;padding:10px 18px;border-bottom:1px solid #F0F4F8;">Mode de paiement</td>
            <td style="font-size:13px;font-weight:600;color:#0F2235;text-align:right;padding:10px 18px;border-bottom:1px solid #F0F4F8;">{methode_label}</td>
          </tr>
          <tr>
            <td style="color:#0F2235;font-size:14px;font-weight:700;padding:14px 18px;">Montant payé</td>
            <td style="font-size:17px;font-weight:700;color:#C4973A;text-align:right;padding:14px 18px;">{montant:.2f} DT</td>
          </tr>
        </table>

        <!-- Note PDF -->
        <div style="margin:24px 0 0;background:#EBF4FF;border:1px solid rgba(26,63,99,0.2);
                    border-radius:10px;padding:14px 18px;">
          <p style="color:#1A3F63;font-size:13px;margin:0;line-height:1.5;">
            📎 <strong>Votre voucher PDF</strong> est joint à cet email.
            Téléchargez-le et présentez-le (imprimé ou sur smartphone)
            à la réception de l'hôtel lors de votre arrivée.
          </p>
        </div>
      </td></tr>

      <!-- Pied de page -->
      <tr><td style="background:#F8FAFC;padding:20px 44px;text-align:center;
                     border-top:1px solid #EEF2F7;">
        <p style="color:#B0BEC8;font-size:12px;margin:0 0 4px;">
          EasyVoyage — La plateforme tunisienne de réservation
        </p>
        <p style="color:#C8D0DA;font-size:11px;margin:0;">
          📧 contact@easyvoyage.tn · 📞 +216 XX XXX XXX
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""

    try:
        await asyncio.to_thread(
            _send_voucher_sync,
            to, subject, html, pdf_bytes, pdf_filename,
        )
    except Exception as exc:
        # Ne jamais crasher — la réservation est déjà confirmée en base
        print(f"[EMAIL VOUCHER] ❌ Échec envoi à '{to}': {exc}")