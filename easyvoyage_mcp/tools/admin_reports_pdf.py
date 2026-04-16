"""
mcp/tools/admin_reports_pdf.py
================================
Tools MCP — Génération de rapports PDF téléchargeables.
Mini serveur HTTP intégré pour servir les fichiers.

Tools :
  admin_rapport_pdf → rapport complet EasyVoyage (KPIs + top hôtels + top partenaires + évolution)
"""

import json
import os
import threading
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
FILE_SERVER_PORT = int(os.getenv("MCP_FILE_SERVER_PORT", "8766"))
FILE_SERVER_HOST = "localhost"

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
#  MINI SERVEUR HTTP
# ══════════════════════════════════════════════════════════

_server_started = False


def _start_file_server():
    global _server_started
    if _server_started:
        return
    _server_started = True
    abs_dir = os.path.abspath(PDF_DIR)
    os.makedirs(abs_dir, exist_ok=True)

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
        srv = HTTPServer((FILE_SERVER_HOST, FILE_SERVER_PORT), _Handler)
        srv.serve_forever()

    threading.Thread(target=_run, daemon=True).start()


# ══════════════════════════════════════════════════════════
#  COLLECTE DES DONNÉES POUR LE PDF
# ══════════════════════════════════════════════════════════

def _collect_report_data() -> dict:
    kpis = db_fetchrow("""
        SELECT
            (SELECT COUNT(*) FROM hotel WHERE actif=true)                                 AS nb_hotels_actifs,
            (SELECT COUNT(*) FROM utilisateur WHERE role='CLIENT' AND actif=true)         AS nb_clients_actifs,
            (SELECT COUNT(*) FROM utilisateur WHERE role='PARTENAIRE' AND actif=true)     AS nb_partenaires_actifs,
            (SELECT COUNT(*) FROM reservation WHERE statut='CONFIRMEE')                   AS nb_reservations_clients,
            (SELECT COUNT(*) FROM reservation_visiteur WHERE statut='CONFIRMEE')          AS nb_reservations_visiteurs,
            (SELECT COALESCE(SUM(total_ttc),0) FROM reservation WHERE statut='CONFIRMEE')          AS ca_clients,
            (SELECT COALESCE(SUM(total_ttc),0) FROM reservation_visiteur WHERE statut='CONFIRMEE') AS ca_visiteurs,
            (SELECT COUNT(*) FROM promotion WHERE statut='PENDING')                       AS nb_promos_en_attente
    """)

    evolution = db_fetch("""
        SELECT
            TO_CHAR(date_reservation, 'YYYY-MM') AS mois,
            COUNT(*)                             AS nb_reservations,
            COALESCE(SUM(total_ttc), 0)          AS ca
        FROM reservation
        WHERE statut='CONFIRMEE'
          AND date_reservation >= NOW() - INTERVAL '12 months'
        GROUP BY TO_CHAR(date_reservation, 'YYYY-MM')
        ORDER BY mois DESC
    """)

    top_hotels = db_fetch("""
        SELECT
            h.id, h.nom, h.ville, h.etoiles,
            COUNT(DISTINCT lrc.id_reservation)     AS nb_reservations,
            COALESCE(SUM(DISTINCT r.total_ttc), 0) AS ca
        FROM hotel h
        LEFT JOIN chambre c                    ON c.id_hotel = h.id
        LEFT JOIN ligne_reservation_chambre lrc ON lrc.id_chambre = c.id
        LEFT JOIN reservation r                ON r.id = lrc.id_reservation
                                               AND r.statut = 'CONFIRMEE'
        GROUP BY h.id
        ORDER BY ca DESC
        LIMIT 10
    """)

    top_partenaires = db_fetch("""
        SELECT
            u.nom || ' ' || u.prenom AS partenaire_nom,
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

    ca_total = float(kpis.get("ca_clients") or 0) + float(kpis.get("ca_visiteurs") or 0)
    kpis["ca_total"] = round(ca_total, 2)

    return {
        "kpis":               kpis,
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

    title_s   = _ps("T1", fontName="Helvetica-Bold", fontSize=20, textColor=WHITE,      leading=26, alignment=TA_LEFT)
    sub_s     = _ps("T2", fontName="Helvetica",       fontSize=9,  textColor=GOLD_LIGHT, leading=13, alignment=TA_LEFT)
    section_s = _ps("S1", fontName="Helvetica-Bold",  fontSize=12, textColor=NAVY,       leading=16, spaceAfter=5, spaceBefore=10)
    kpi_lbl   = _ps("KL", fontName="Helvetica",       fontSize=8,  textColor=GRAY,       leading=10, alignment=TA_CENTER)
    kpi_val   = _ps("KV", fontName="Helvetica-Bold",  fontSize=17, textColor=NAVY,       leading=21, alignment=TA_CENTER)
    kpi_sub   = _ps("KS", fontName="Helvetica",       fontSize=7,  textColor=BLUE_L,     leading=9,  alignment=TA_CENTER)
    th_s      = _ps("TH", fontName="Helvetica-Bold",  fontSize=8,  textColor=WHITE,      alignment=TA_CENTER, leading=10)
    td_c      = _ps("TC", fontName="Helvetica",       fontSize=8,  textColor=colors.HexColor("#1e293b"), alignment=TA_CENTER, leading=11)
    td_l      = _ps("TL", fontName="Helvetica",       fontSize=8,  textColor=colors.HexColor("#1e293b"), alignment=TA_LEFT,   leading=11)
    footer_s  = _ps("FT", fontName="Helvetica",       fontSize=7,  textColor=GRAY,       alignment=TA_CENTER)

    story = []
    now   = datetime.now().strftime("%d/%m/%Y à %H:%M")

    # Bannière titre
    h_tbl = Table(
        [[Paragraph("RAPPORT ADMIN — EasyVoyage", title_s),
          Paragraph(f"Généré le {now}", sub_s)]],
        colWidths=[11*cm, 6.5*cm],
    )
    h_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("PADDING",    (0, 0), (-1, -1), 16),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",      (1, 0), (1,  0),  "RIGHT"),
        ("LINEBELOW",  (0, 0), (-1, -1), 3, GOLD),
    ]))
    story += [h_tbl, Spacer(1, 0.6*cm)]

    # KPIs
    kpis = data.get("kpis", {})
    ca_t = float(kpis.get("ca_total") or 0)

    def kpi_cell(label, value, sub, accent):
        t = Table(
            [[Paragraph(label, kpi_lbl)],
             [Paragraph(str(value), kpi_val)],
             [Paragraph(sub, kpi_sub)]],
            colWidths=[3.8*cm],
        )
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), WHITE),
            ("BOX",           (0, 0), (-1, -1), 1.5, accent),
            ("LINEABOVE",     (0, 0), (-1,  0), 4,   accent),
            ("TOPPADDING",    (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ]))
        return t

    kpi_row = [[
        kpi_cell("HÔTELS ACTIFS",    kpis.get("nb_hotels_actifs", 0),      "sur plateforme", BLUE),
        kpi_cell("CLIENTS ACTIFS",   kpis.get("nb_clients_actifs", 0),     "inscrits",        GREEN),
        kpi_cell("RÉSERVATIONS",
                 int(kpis.get("nb_reservations_clients", 0)) +
                 int(kpis.get("nb_reservations_visiteurs", 0)),             "total confirmées", GOLD),
        kpi_cell("CA TOTAL",         f"{ca_t:,.0f}",                       "TND",             ORANGE),
        kpi_cell("PROMOS PENDING",   kpis.get("nb_promos_en_attente", 0),  "à valider",       RED),
    ]]
    kt = Table(kpi_row, colWidths=[3.8*cm]*5, hAlign="CENTER")
    kt.setStyle(TableStyle([
        ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",(0, 0), (-1, -1), 3),
    ]))
    story += [kt, Spacer(1, 0.6*cm)]

    # Top Hôtels
    top_hotels = data.get("top_hotels", [])
    if top_hotels:
        story += [
            Paragraph("Top Hôtels par Chiffre d'Affaires", section_s),
            HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=6),
        ]
        hd = [[Paragraph(h, th_s) for h in ["#", "HÔTEL", "VILLE", "ÉTOILES", "RÉSERVATIONS", "CA (TND)"]]]
        for i, h in enumerate(top_hotels[:10], 1):
            hd.append([
                Paragraph(str(i), td_c),
                Paragraph(str(h.get("nom", "—")), td_l),
                Paragraph(str(h.get("ville", "—")), td_c),
                Paragraph("★" * int(h.get("etoiles") or 0), td_c),
                Paragraph(str(h.get("nb_reservations", 0)), td_c),
                Paragraph(f"{float(h.get('ca') or 0):,.2f}", td_c),
            ])
        ht = Table(hd, colWidths=[1*cm, 5.5*cm, 3*cm, 2*cm, 3*cm, 3*cm], repeatRows=1)
        ht.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1,  0), NAVY),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, GRAY_LIGHT]),
            ("GRID",          (0, 0), (-1, -1), 0.5, BORDER),
            ("BOX",           (0, 0), (-1, -1), 1, GOLD),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story += [ht, Spacer(1, 0.5*cm)]

    # Top Partenaires
    top_part = data.get("top_partenaires", [])
    if top_part:
        story += [
            Paragraph("Top Partenaires par Commissions", section_s),
            HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=6),
        ]
        pd_data = [[Paragraph(h, th_s) for h in ["#", "PARTENAIRE", "ENTREPRISE", "HÔTELS", "COMMISSIONS (TND)"]]]
        for i, p in enumerate(top_part[:10], 1):
            pd_data.append([
                Paragraph(str(i), td_c),
                Paragraph(str(p.get("partenaire_nom", "—")), td_l),
                Paragraph(str(p.get("nom_entreprise", "—")), td_l),
                Paragraph(str(p.get("nb_hotels", 0)), td_c),
                Paragraph(f"{float(p.get('total_commissions') or 0):,.2f}", td_c),
            ])
        pt = Table(pd_data, colWidths=[1*cm, 4.5*cm, 4.5*cm, 2*cm, 4.5*cm], repeatRows=1)
        pt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1,  0), NAVY),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, GRAY_LIGHT]),
            ("GRID",          (0, 0), (-1, -1), 0.5, BORDER),
            ("BOX",           (0, 0), (-1, -1), 1, BLUE),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story += [pt, Spacer(1, 0.5*cm)]

    # Évolution mensuelle
    monthly = data.get("evolution_mensuelle", [])
    if monthly:
        story += [
            Paragraph("Évolution Mensuelle — 12 Derniers Mois", section_s),
            HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=6),
        ]
        md = [[Paragraph(h, th_s) for h in ["MOIS", "NB RÉSERVATIONS", "CA (TND)"]]]
        for m in monthly:
            md.append([
                Paragraph(str(m.get("mois", "—")), td_c),
                Paragraph(str(m.get("nb_reservations", 0)), td_c),
                Paragraph(f"{float(m.get('ca') or 0):,.2f}", td_c),
            ])
        mt = Table(md, colWidths=[4*cm, 6*cm, 6.5*cm], repeatRows=1)
        mt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1,  0), NAVY),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, GRAY_LIGHT]),
            ("GRID",          (0, 0), (-1, -1), 0.5, BORDER),
            ("BOX",           (0, 0), (-1, -1), 1, GREEN),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story += [mt, Spacer(1, 0.5*cm)]

    story += [
        HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceBefore=8, spaceAfter=5),
        Paragraph(
            "Rapport confidentiel — généré automatiquement par le système MCP Admin EasyVoyage",
            footer_s
        ),
    ]
    doc.build(story)


# ══════════════════════════════════════════════════════════
#  TOOL MCP
# ══════════════════════════════════════════════════════════

@mcp.tool(description=(
    "Générer un rapport PDF complet de l'espace admin EasyVoyage "
    "et retourner un lien de téléchargement direct cliquable. "
    "Contenu du PDF : KPIs globaux (hôtels, clients, réservations, CA total, promos en attente), "
    "top 10 hôtels par CA, top 10 partenaires par commissions, "
    "évolution mensuelle sur 12 mois. "
    "Aucun paramètre requis."
))
def admin_rapport_pdf() -> str:
    try:
        _start_file_server()

        data = _collect_report_data()

        os.makedirs(PDF_DIR, exist_ok=True)
        filename    = f"rapport_admin_easyvoyage_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        output_path = os.path.join(os.path.abspath(PDF_DIR), filename)

        _build_pdf(data, output_path)

        url = f"http://{FILE_SERVER_HOST}:{FILE_SERVER_PORT}/{filename}"

        return json.dumps({
            "ok":           True,
            "message":      "Rapport PDF prêt — cliquez sur le lien pour télécharger.",
            "download_link": url,
            "filename":     filename,
            "generated_at": datetime.now().strftime("%d/%m/%Y à %H:%M:%S"),
            "sections": [
                "KPIs globaux (hôtels, clients, réservations, CA total)",
                "Top 10 hôtels par CA",
                "Top 10 partenaires par commissions",
                "Évolution mensuelle 12 mois",
            ],
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)