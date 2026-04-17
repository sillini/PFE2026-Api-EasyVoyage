"""
mcp/tools/admin_reports_pdf.py
================================
VERSION CORRIGÉE — séparation propre des ports

Tools MCP — Génération de rapports PDF téléchargeables.
Mini serveur HTTP intégré pour servir les fichiers.

═══════════════════════════════════════════════════════════════════
BUG CRITIQUE CORRIGÉ
═══════════════════════════════════════════════════════════════════
  v1 → v2 : CONFLIT DE PORT
    Le mini-serveur HTTP utilisait le port 8766 par défaut,
    qui est DEJA occupé par run_mcp_finances.py !
    → Ça crashait le serveur Finances à la premiere generation PDF.

    Correction :
      - Port mini-serveur HTTP par defaut : 8768 (libre)
      - Detection du conflit : si le port est occupe, on increment jusqu'a trouver libre
      - Logs detailles en cas d'echec

  v2 → v3 : amelioration de robustesse
    - L'erreur complete est retournee dans le JSON en cas d'echec
    - Le serveur HTTP n'est demarre qu'une fois
    - Gestion propre des exceptions

Tools :
  admin_rapport_pdf → rapport complet EasyVoyage (KPIs + top hôtels + top partenaires + évolution)
"""

import json
import os
import socket
import threading
import traceback
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

from mcp.server.fastmcp import FastMCP
from easyvoyage_mcp.database import db_fetch, db_fetchrow

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

mcp = FastMCP("easyvoyage-admin-mcp")

PDF_DIR          = os.getenv("MCP_PDF_DIR", "./mcp_reports")
# ⚠️  Port 8768 (libre) — JAMAIS 8766 (utilise par run_mcp_finances.py)
FILE_SERVER_PORT = int(os.getenv("MCP_FILE_SERVER_PORT", "8768"))
FILE_SERVER_HOST = "localhost"
TAUX_COMMISSION  = 10.0

# ── Charte couleurs EasyVoyage ────────────────────────────
NAVY       = colors.HexColor("#0F2235")
GOLD       = colors.HexColor("#C4973A")
GOLD_LIGHT = colors.HexColor("#F5EDD6")
BLUE       = colors.HexColor("#1A3F63")
BLUE_L     = colors.HexColor("#3B82F6")
GREEN      = colors.HexColor("#10b981")
RED        = colors.HexColor("#ef4444")
ORANGE     = colors.HexColor("#f59e0b")
WHITE      = colors.white
GRAY_LIGHT = colors.HexColor("#F1F5F9")
GRAY       = colors.HexColor("#64748B")
BORDER     = colors.HexColor("#E2E8F0")


def _ps(name, **kw):
    return ParagraphStyle(name, **kw)


# ══════════════════════════════════════════════════════════
#  MINI SERVEUR HTTP — detection automatique de port libre
# ══════════════════════════════════════════════════════════

_server_started = False
_actual_port    = None  # Port reellement utilise apres detection


def _is_port_free(port: int) -> bool:
    """Verifie si un port TCP est libre en essayant de s'y lier brievement."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((FILE_SERVER_HOST, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _find_free_port(start: int, max_tries: int = 10) -> int:
    """Trouve un port libre en partant de `start`. Leve si aucun trouve."""
    for p in range(start, start + max_tries):
        if _is_port_free(p):
            return p
    raise RuntimeError(
        f"Aucun port libre trouve entre {start} et {start + max_tries - 1}. "
        f"Verifiez vos serveurs actifs avec : netstat -ano | findstr LISTENING"
    )


def _start_file_server():
    """Demarre le mini-serveur HTTP une seule fois, sur un port libre."""
    global _server_started, _actual_port
    if _server_started:
        return

    abs_dir = os.path.abspath(PDF_DIR)
    os.makedirs(abs_dir, exist_ok=True)

    # Trouve un port libre (commence par celui configure, puis incremente)
    _actual_port = _find_free_port(FILE_SERVER_PORT)

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=abs_dir, **kwargs)

        def end_headers(self):
            if self.path.endswith(".pdf"):
                fname = os.path.basename(self.path)
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

        def log_message(self, *args):
            pass

    def _run():
        try:
            srv = HTTPServer((FILE_SERVER_HOST, _actual_port), _Handler)
            srv.serve_forever()
        except Exception as e:
            print(f"[MCP PDF SERVER] Erreur demarrage sur port {_actual_port}: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    _server_started = True
    print(f"[MCP PDF SERVER] Demarre sur http://{FILE_SERVER_HOST}:{_actual_port}")


# ══════════════════════════════════════════════════════════
#  COLLECTE DES DONNÉES POUR LE PDF
# ══════════════════════════════════════════════════════════

def _collect_report_data() -> dict:
    # ── KPIs globaux ─────────────────────────────────────
    kpis = db_fetchrow("""
        SELECT
            (SELECT COUNT(*) FROM hotel WHERE actif=true)                              AS nb_hotels_actifs,
            (SELECT COUNT(*) FROM utilisateur WHERE role='CLIENT' AND actif=true)      AS nb_clients_actifs,
            (SELECT COUNT(*) FROM utilisateur WHERE role='PARTENAIRE' AND actif=true)  AS nb_partenaires_actifs,

            (SELECT COUNT(*) FROM reservation
             WHERE id_voyage IS NULL
               AND statut IN ('CONFIRMEE','TERMINEE'))                                 AS nb_resa_hotel_clients,

            (SELECT COUNT(*) FROM reservation
             WHERE id_voyage IS NOT NULL
               AND statut IN ('CONFIRMEE','TERMINEE'))                                 AS nb_resa_voyage_clients,

            (SELECT COUNT(*) FROM reservation_visiteur
             WHERE statut IN ('CONFIRMEE','TERMINEE'))                                 AS nb_resa_hotel_visiteurs,

            (SELECT COALESCE(SUM(total_ttc),0) FROM reservation
             WHERE id_voyage IS NULL
               AND statut IN ('CONFIRMEE','TERMINEE'))                                 AS ca_hotel_clients,

            (SELECT COALESCE(SUM(total_ttc),0) FROM reservation
             WHERE id_voyage IS NOT NULL
               AND statut IN ('CONFIRMEE','TERMINEE'))                                 AS ca_voyage_clients,

            (SELECT COALESCE(SUM(total_ttc),0) FROM reservation_visiteur
             WHERE statut IN ('CONFIRMEE','TERMINEE'))                                 AS ca_hotel_visiteurs,

            (SELECT COUNT(*) FROM promotion WHERE CAST(statut AS VARCHAR)='PENDING')   AS nb_promos_en_attente
    """)

    ca_hotel_clients   = float(kpis.get("ca_hotel_clients")   or 0)
    ca_voyage_clients  = float(kpis.get("ca_voyage_clients")  or 0)
    ca_hotel_visiteurs = float(kpis.get("ca_hotel_visiteurs") or 0)
    ca_hotel_total     = ca_hotel_clients + ca_hotel_visiteurs
    ca_total           = ca_hotel_total + ca_voyage_clients
    commission_agence  = round(ca_hotel_total * TAUX_COMMISSION / 100, 2)
    part_partenaires   = round(ca_hotel_total - commission_agence, 2)

    kpis["ca_hotel_total"]    = round(ca_hotel_total, 2)
    kpis["ca_voyage_total"]   = round(ca_voyage_clients, 2)
    kpis["ca_total"]          = round(ca_total, 2)
    kpis["commission_agence"] = commission_agence
    kpis["part_partenaires"]  = part_partenaires
    kpis["nb_resa_total"] = (
        int(kpis.get("nb_resa_hotel_clients")   or 0) +
        int(kpis.get("nb_resa_voyage_clients")  or 0) +
        int(kpis.get("nb_resa_hotel_visiteurs") or 0)
    )

    # ── Évolution mensuelle — toutes sources ─────────────
    evolution = db_fetch("""
        SELECT
            mois,
            SUM(nb_hotel_clients)   AS nb_hotel_clients,
            SUM(nb_voyage_clients)  AS nb_voyage_clients,
            SUM(nb_hotel_visiteurs) AS nb_hotel_visiteurs,
            SUM(nb_hotel_clients) + SUM(nb_voyage_clients) + SUM(nb_hotel_visiteurs) AS nb_total,
            SUM(ca_hotel_clients)   AS ca_hotel_clients,
            SUM(ca_voyage_clients)  AS ca_voyage_clients,
            SUM(ca_hotel_visiteurs) AS ca_hotel_visiteurs,
            SUM(ca_hotel_clients) + SUM(ca_voyage_clients) + SUM(ca_hotel_visiteurs) AS ca_total,
            ROUND((SUM(ca_hotel_clients) + SUM(ca_hotel_visiteurs)) * 10.0 / 100, 2) AS commission_agence
        FROM (
            SELECT
                TO_CHAR(date_reservation, 'YYYY-MM')  AS mois,
                SUM(CASE WHEN id_voyage IS NULL  THEN 1 ELSE 0 END) AS nb_hotel_clients,
                SUM(CASE WHEN id_voyage IS NOT NULL THEN 1 ELSE 0 END) AS nb_voyage_clients,
                0 AS nb_hotel_visiteurs,
                COALESCE(SUM(CASE WHEN id_voyage IS NULL THEN total_ttc END), 0)     AS ca_hotel_clients,
                COALESCE(SUM(CASE WHEN id_voyage IS NOT NULL THEN total_ttc END), 0) AS ca_voyage_clients,
                0 AS ca_hotel_visiteurs
            FROM reservation
            WHERE statut IN ('CONFIRMEE','TERMINEE')
              AND date_reservation >= NOW() - INTERVAL '12 months'
            GROUP BY TO_CHAR(date_reservation, 'YYYY-MM')

            UNION ALL

            SELECT
                TO_CHAR(created_at, 'YYYY-MM')       AS mois,
                0 AS nb_hotel_clients,
                0 AS nb_voyage_clients,
                COUNT(*)                             AS nb_hotel_visiteurs,
                0 AS ca_hotel_clients,
                0 AS ca_voyage_clients,
                COALESCE(SUM(total_ttc), 0)          AS ca_hotel_visiteurs
            FROM reservation_visiteur
            WHERE statut IN ('CONFIRMEE','TERMINEE')
              AND created_at >= NOW() - INTERVAL '12 months'
            GROUP BY TO_CHAR(created_at, 'YYYY-MM')
        ) combined
        GROUP BY mois
        ORDER BY mois DESC
    """)

    # ── Top 10 hôtels (clients + visiteurs) ──────────────
    top_hotels = db_fetch("""
        SELECT
            h.id, h.nom, h.ville, h.etoiles,
            COALESCE(ca_c.nb, 0) + COALESCE(ca_v.nb, 0)     AS nb_reservations,
            COALESCE(ca_c.ca, 0) + COALESCE(ca_v.ca, 0)     AS ca,
            ROUND((COALESCE(ca_c.ca, 0) + COALESCE(ca_v.ca, 0)) * 10.0 / 100, 2) AS commission_agence
        FROM hotel h
        LEFT JOIN (
            SELECT c.id_hotel,
                   COUNT(DISTINCT r.id)          AS nb,
                   COALESCE(SUM(r.total_ttc), 0) AS ca
            FROM reservation r
            JOIN ligne_reservation_chambre lrc ON lrc.id_reservation = r.id
            JOIN chambre c ON c.id = lrc.id_chambre
            WHERE r.id_voyage IS NULL
              AND r.statut IN ('CONFIRMEE','TERMINEE')
            GROUP BY c.id_hotel
        ) ca_c ON ca_c.id_hotel = h.id
        LEFT JOIN (
            SELECT c.id_hotel,
                   COUNT(DISTINCT rv.id)          AS nb,
                   COALESCE(SUM(rv.total_ttc), 0) AS ca
            FROM reservation_visiteur rv
            JOIN chambre c ON c.id = rv.id_chambre
            WHERE rv.statut IN ('CONFIRMEE','TERMINEE')
            GROUP BY c.id_hotel
        ) ca_v ON ca_v.id_hotel = h.id
        ORDER BY ca DESC
        LIMIT 10
    """)

    # ── Top 10 partenaires ────────────────────────────────
    # ⚠️  Colonne = "statut" (pas "statut_commission")
    top_partenaires = db_fetch("""
        SELECT
            u.nom || ' ' || u.prenom               AS partenaire_nom,
            p.nom_entreprise,
            COUNT(DISTINCT h.id)                   AS nb_hotels,
            COALESCE(SUM(cp.montant_commission), 0) AS total_commissions
        FROM utilisateur u
        JOIN partenaire p ON p.id = u.id
        LEFT JOIN hotel h                  ON h.id_partenaire = u.id
        LEFT JOIN commission_partenaire cp ON cp.id_partenaire = u.id
        WHERE u.role = 'PARTENAIRE'
        GROUP BY u.id, p.nom_entreprise
        ORDER BY total_commissions DESC
        LIMIT 10
    """)

    return {
        "kpis":                kpis,
        "evolution_mensuelle": evolution,
        "top_hotels":          top_hotels,
        "top_partenaires":     top_partenaires,
    }


# ══════════════════════════════════════════════════════════
#  GÉNÉRATEUR PDF
# ══════════════════════════════════════════════════════════

def _build_pdf(data: dict, output_path: str):
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=1.5*cm, bottomMargin=2*cm,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
    )

    section_s = _ps("S1", fontName="Helvetica-Bold",  fontSize=12, textColor=NAVY,  leading=16, spaceAfter=5, spaceBefore=10)
    kpi_lbl   = _ps("KL", fontName="Helvetica",        fontSize=8,  textColor=GRAY,  leading=10, alignment=TA_CENTER)
    th_s      = _ps("TH", fontName="Helvetica-Bold",   fontSize=8,  textColor=WHITE, alignment=TA_CENTER, leading=10)
    td_c      = _ps("TC", fontName="Helvetica",        fontSize=8,  textColor=colors.HexColor("#1e293b"), alignment=TA_CENTER, leading=11)
    td_l      = _ps("TL", fontName="Helvetica",        fontSize=8,  textColor=colors.HexColor("#1e293b"), alignment=TA_LEFT,   leading=11)
    title_s   = _ps("T1", fontName="Helvetica-Bold",   fontSize=20, textColor=WHITE, leading=26, alignment=TA_LEFT)
    sub_s     = _ps("T2", fontName="Helvetica",        fontSize=9,  textColor=GOLD_LIGHT, leading=13, alignment=TA_LEFT)
    footer_s  = _ps("FT", fontName="Helvetica",        fontSize=7,  textColor=GRAY,  leading=9,  alignment=TA_CENTER)

    kpis  = data.get("kpis", {})
    story = []

    # ── Banniere ──────────────────────────────────────────
    banner = Table([[
        Paragraph("EasyVoyage - Rapport Admin", title_s),
        Paragraph(f"Genere le {datetime.now().strftime('%d/%m/%Y a %H:%M')}", sub_s),
    ]], colWidths=[13*cm, 5*cm])
    banner.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), NAVY),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [banner, Spacer(1, 0.6*cm)]

    # ── KPIs globaux ──────────────────────────────────────
    story.append(Paragraph("KPIs Globaux", section_s))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=8))

    kpi_items = [
        ("Hotels actifs",          kpis.get("nb_hotels_actifs", 0)),
        ("Clients actifs",          kpis.get("nb_clients_actifs", 0)),
        ("Partenaires actifs",      kpis.get("nb_partenaires_actifs", 0)),
        ("Reservations hotel",      f"{int(kpis.get('nb_resa_hotel_clients',0)) + int(kpis.get('nb_resa_hotel_visiteurs',0))}  (clients+visiteurs)"),
        ("Reservations voyage",     kpis.get("nb_resa_voyage_clients", 0)),
        ("CA hotel total",          f"{float(kpis.get('ca_hotel_total') or 0):,.2f} TND"),
        ("CA voyage",               f"{float(kpis.get('ca_voyage_total') or 0):,.2f} TND"),
        ("CA total",                f"{float(kpis.get('ca_total') or 0):,.2f} TND"),
        ("Commission agence (10%)", f"{float(kpis.get('commission_agence') or 0):,.2f} TND"),
        ("Part partenaires (90%)",  f"{float(kpis.get('part_partenaires') or 0):,.2f} TND"),
        ("Promos en attente",       kpis.get("nb_promos_en_attente", 0)),
    ]

    kpi_rows = []
    row = []
    for i, (lbl, val) in enumerate(kpi_items):
        row.append(Paragraph(f"<b>{val}</b><br/><font size=7>{lbl}</font>", kpi_lbl))
        if len(row) == 3 or i == len(kpi_items) - 1:
            while len(row) < 3:
                row.append(Paragraph("", kpi_lbl))
            kpi_rows.append(row)
            row = []

    kpi_table = Table(kpi_rows, colWidths=[5.8*cm, 5.8*cm, 5.8*cm])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), GRAY_LIGHT),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("GRID",          (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [kpi_table, Spacer(1, 0.5*cm)]

    # ── Top 10 hotels ─────────────────────────────────────
    top_hotels = data.get("top_hotels", [])
    if top_hotels:
        story += [
            Paragraph("Top 10 Hotels par CA (clients + visiteurs)", section_s),
            HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=6),
        ]
        hd = [[Paragraph(h, th_s) for h in ["#", "HOTEL", "VILLE", "*", "RESAS", "CA (TND)", "COMMISSION 10%"]]]
        for i, h in enumerate(top_hotels, 1):
            hd.append([
                Paragraph(str(i),                                                         td_c),
                Paragraph(str(h.get("nom", "-")),                                        td_l),
                Paragraph(str(h.get("ville", "-")),                                      td_c),
                Paragraph(str(h.get("etoiles", "-")),                                    td_c),
                Paragraph(str(h.get("nb_reservations", 0)),                               td_c),
                Paragraph(f"{float(h.get('ca') or 0):,.2f}",                             td_c),
                Paragraph(f"{float(h.get('commission_agence') or 0):,.2f}",              td_c),
            ])
        ht = Table(hd, colWidths=[0.8*cm, 4.5*cm, 3*cm, 1*cm, 1.8*cm, 3*cm, 3.5*cm], repeatRows=1)
        ht.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1,  0), NAVY),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, GRAY_LIGHT]),
            ("GRID",          (0, 0), (-1, -1), 0.5, BORDER),
            ("BOX",           (0, 0), (-1, -1), 1, BLUE),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story += [ht, Spacer(1, 0.5*cm)]

    # ── Top 10 partenaires ────────────────────────────────
    top_partenaires = data.get("top_partenaires", [])
    if top_partenaires:
        story += [
            Paragraph("Top 10 Partenaires par Commissions", section_s),
            HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=6),
        ]
        pd_rows = [[Paragraph(h, th_s) for h in ["#", "PARTENAIRE", "ENTREPRISE", "NB HOTELS", "COMMISSIONS (TND)"]]]
        for i, p in enumerate(top_partenaires, 1):
            pd_rows.append([
                Paragraph(str(i),                                                          td_c),
                Paragraph(str(p.get("partenaire_nom", "-")),                              td_l),
                Paragraph(str(p.get("nom_entreprise", "-")),                              td_l),
                Paragraph(str(p.get("nb_hotels", 0)),                                      td_c),
                Paragraph(f"{float(p.get('total_commissions') or 0):,.2f}",               td_c),
            ])
        pt = Table(pd_rows, colWidths=[1*cm, 5*cm, 5*cm, 2.5*cm, 4.2*cm], repeatRows=1)
        pt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1,  0), NAVY),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, GRAY_LIGHT]),
            ("GRID",          (0, 0), (-1, -1), 0.5, BORDER),
            ("BOX",           (0, 0), (-1, -1), 1, BLUE),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story += [pt, Spacer(1, 0.5*cm)]

    # ── Evolution mensuelle ───────────────────────────────
    monthly = data.get("evolution_mensuelle", [])
    if monthly:
        story += [
            Paragraph("Evolution Mensuelle - 12 Derniers Mois", section_s),
            HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=6),
        ]
        md = [[Paragraph(h, th_s) for h in [
            "MOIS", "RESAS HOTEL", "RESAS VOYAGE", "CA HOTEL (TND)", "CA VOYAGE (TND)", "CA TOTAL (TND)", "COMMISSION 10%"
        ]]]
        for m in monthly:
            nb_hotel = int(m.get("nb_hotel_clients", 0) or 0) + int(m.get("nb_hotel_visiteurs", 0) or 0)
            md.append([
                Paragraph(str(m.get("mois", "-")),                                    td_c),
                Paragraph(str(nb_hotel),                                               td_c),
                Paragraph(str(m.get("nb_voyage_clients", 0)),                          td_c),
                Paragraph(f"{float(m.get('ca_hotel_clients',0) or 0) + float(m.get('ca_hotel_visiteurs',0) or 0):,.2f}", td_c),
                Paragraph(f"{float(m.get('ca_voyage_clients') or 0):,.2f}",            td_c),
                Paragraph(f"{float(m.get('ca_total') or 0):,.2f}",                    td_c),
                Paragraph(f"{float(m.get('commission_agence') or 0):,.2f}",           td_c),
            ])
        mt = Table(md, colWidths=[2.2*cm, 2.5*cm, 2.5*cm, 3*cm, 3*cm, 3*cm, 2.5*cm], repeatRows=1)
        mt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1,  0), NAVY),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, GRAY_LIGHT]),
            ("GRID",          (0, 0), (-1, -1), 0.5, BORDER),
            ("BOX",           (0, 0), (-1, -1), 1, GREEN),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ]))
        story += [mt, Spacer(1, 0.5*cm)]

    # ── Pied de page ──────────────────────────────────────
    story += [
        HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceBefore=8, spaceAfter=5),
        Paragraph(
            "Rapport confidentiel - genere automatiquement par le systeme MCP Admin EasyVoyage",
            footer_s
        ),
    ]
    doc.build(story)


# ══════════════════════════════════════════════════════════
#  TOOL MCP
# ══════════════════════════════════════════════════════════

@mcp.tool(description=(
    "Generer un rapport PDF complet de l'espace admin EasyVoyage "
    "et retourner un lien de telechargement direct cliquable. "
    "Contenu : KPIs globaux (CA hotel/voyage/total, commission 10% sur hotels, part partenaires), "
    "top 10 hotels par CA, top 10 partenaires par commissions, "
    "evolution mensuelle 12 mois (hotel + voyage + visiteurs). "
    "Aucun parametre requis."
))
def admin_rapport_pdf() -> str:
    try:
        _start_file_server()

        data = _collect_report_data()

        os.makedirs(PDF_DIR, exist_ok=True)
        filename    = f"rapport_admin_easyvoyage_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        output_path = os.path.join(os.path.abspath(PDF_DIR), filename)

        _build_pdf(data, output_path)

        # Utiliser le port reellement alloue (peut differer de FILE_SERVER_PORT si conflit)
        port = _actual_port or FILE_SERVER_PORT
        url  = f"http://{FILE_SERVER_HOST}:{port}/{filename}"

        return json.dumps({
            "ok":            True,
            "message":       "Rapport PDF pret - cliquez sur le lien pour telecharger.",
            "download_link": url,
            "filename":      filename,
            "generated_at":  datetime.now().strftime("%d/%m/%Y a %H:%M:%S"),
            "sections": [
                "KPIs globaux (CA hotel/voyage/total, commission 10% hotels, part partenaires)",
                "Top 10 hotels par CA (clients + visiteurs)",
                "Top 10 partenaires par commissions",
                "Evolution mensuelle 12 mois (hotel + voyage + visiteurs)",
            ],
        }, indent=2, ensure_ascii=False)

    except Exception as e:
        # Retourner la trace complete pour faciliter le debug
        return json.dumps({
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }, indent=2, ensure_ascii=False)