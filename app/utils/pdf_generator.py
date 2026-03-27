"""
Générateur de factures PDF avec ReportLab.

Contenu :
  - En-tête : nom de l'agence + titre FACTURE + numéro
  - Informations client
  - Détail des prestations (voyage ou chambres)
  - Tableau récapitulatif des montants
  - Total TTC
  - Pied de page : mentions légales + numéro de page
"""
import io
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Palette de couleurs ───────────────────────────────────────────────────────
BLEU_AGENCE   = colors.HexColor("#1B4F72")   # bleu marine — en-tête
BLEU_CLAIR    = colors.HexColor("#D6EAF8")   # bleu pâle — fond tableau header
GRIS_LEGER    = colors.HexColor("#F2F3F4")   # fond lignes alternées
GRIS_TEXTE    = colors.HexColor("#555555")   # texte secondaire
VERT_TOTAL    = colors.HexColor("#1E8449")   # montant total


def _get_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="AgenceNom",
        fontSize=22, fontName="Helvetica-Bold",
        textColor=BLEU_AGENCE, spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name="AgenceSlogan",
        fontSize=9, fontName="Helvetica",
        textColor=GRIS_TEXTE, spaceAfter=0,
    ))
    styles.add(ParagraphStyle(
        name="TitreFacture",
        fontSize=26, fontName="Helvetica-Bold",
        textColor=BLEU_AGENCE, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="NumeroFacture",
        fontSize=11, fontName="Helvetica",
        textColor=GRIS_TEXTE,
    ))
    styles.add(ParagraphStyle(
        name="SectionTitre",
        fontSize=11, fontName="Helvetica-Bold",
        textColor=BLEU_AGENCE, spaceBefore=12, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="InfoLabel",
        fontSize=9, fontName="Helvetica-Bold",
        textColor=GRIS_TEXTE,
    ))
    styles.add(ParagraphStyle(
        name="InfoValue",
        fontSize=9, fontName="Helvetica",
        textColor=colors.black,
    ))
    styles.add(ParagraphStyle(
        name="PiedPage",
        fontSize=7.5, fontName="Helvetica",
        textColor=GRIS_TEXTE, alignment=1,  # centré
    ))
    return styles


def generer_facture_pdf(
    *,
    # Facture
    numero_facture: str,
    date_emission: datetime,
    statut_facture: str,
    # Client
    client_nom: str,
    client_prenom: str,
    client_email: str,
    client_telephone: Optional[str],
    # Réservation
    date_debut: str,
    date_fin: str,
    nb_nuits: int,
    # Prestations : liste de dicts
    # Pour voyage  : [{"type": "voyage", "titre": "...", "destination": "...", "prix": 1200.00}]
    # Pour chambres: [{"type": "chambre", "description": "...", "nb_nuits": 7, "prix_unitaire": 150.0, "quantite": 1}]
    prestations: list[dict],
    # Montants
    total_ttc: float,
    # Agence
    agence_nom: str = "Voyage Hôtel",
    agence_slogan: str = "Votre partenaire de voyage de confiance",
    agence_adresse: str = "Tunis, Tunisie",
    agence_email: str = "contact@voyagehotel.com",
    agence_tel: str = "+216 XX XXX XXX",
) -> bytes:
    """
    Génère la facture PDF et retourne les bytes.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Facture {numero_facture}",
        author=agence_nom,
    )

    styles = _get_styles()
    elements = []
    largeur = doc.width  # largeur utile

    # ══════════════════════════════════════════════════════
    #  EN-TÊTE : Agence (gauche) + FACTURE (droite)
    # ══════════════════════════════════════════════════════
    entete_data = [[
        # Colonne gauche — Agence
        [
            Paragraph(agence_nom, styles["AgenceNom"]),
            Paragraph(agence_slogan, styles["AgenceSlogan"]),
            Spacer(1, 4),
            Paragraph(agence_adresse, styles["AgenceSlogan"]),
            Paragraph(agence_email, styles["AgenceSlogan"]),
            Paragraph(agence_tel, styles["AgenceSlogan"]),
        ],
        # Colonne droite — FACTURE
        [
            Paragraph("FACTURE", styles["TitreFacture"]),
            Paragraph(f"N° <b>{numero_facture}</b>", styles["NumeroFacture"]),
            Spacer(1, 6),
            Paragraph(
                f"Date d'émission : <b>{date_emission.strftime('%d/%m/%Y')}</b>",
                styles["InfoValue"]
            ),
            Paragraph(
                f"Statut : <b>{statut_facture}</b>",
                styles["InfoValue"]
            ),
        ],
    ]]

    entete_table = Table(entete_data, colWidths=[largeur * 0.55, largeur * 0.45])
    entete_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN",  (1, 0), (1, 0), "RIGHT"),
    ]))
    elements.append(entete_table)
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(HRFlowable(width="100%", thickness=2, color=BLEU_AGENCE))
    elements.append(Spacer(1, 0.4 * cm))

    # ══════════════════════════════════════════════════════
    #  INFORMATIONS CLIENT
    # ══════════════════════════════════════════════════════
    elements.append(Paragraph("Informations client", styles["SectionTitre"]))

    client_data = [
        ["Nom complet",  f"{client_prenom} {client_nom}"],
        ["Email",        client_email],
        ["Téléphone",    client_telephone or "—"],
        ["Période",      f"Du {date_debut} au {date_fin}  ({nb_nuits} nuit(s))"],
    ]

    client_table = Table(client_data, colWidths=[largeur * 0.25, largeur * 0.75])
    client_table.setStyle(TableStyle([
        ("FONTNAME",    (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",    (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",   (0, 0), (0, -1), GRIS_TEXTE),
        ("TEXTCOLOR",   (1, 0), (1, -1), colors.black),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, GRIS_LEGER]),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("GRID",        (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
    ]))
    elements.append(client_table)
    elements.append(Spacer(1, 0.5 * cm))

    # ══════════════════════════════════════════════════════
    #  DÉTAIL DES PRESTATIONS
    # ══════════════════════════════════════════════════════
    elements.append(Paragraph("Détail des prestations", styles["SectionTitre"]))

    # Header du tableau
    presta_header = [["Prestation", "Description", "Qté", "P.U. (TND)", "Total (TND)"]]
    presta_rows = []
    sous_total = 0.0

    for p in prestations:
        if p["type"] == "voyage":
            desc = f"{p['titre']}\nDestination : {p['destination']}"
            qte = "1"
            pu = f"{p['prix']:.3f}"
            total_ligne = p['prix']
            presta_rows.append(["Voyage", desc, qte, pu, f"{total_ligne:.3f}"])
        else:
            desc = p.get("description") or "Chambre standard"
            qte = str(p.get("quantite", 1))
            pu = f"{p['prix_unitaire']:.3f}"
            total_ligne = p['prix_unitaire'] * p.get("quantite", 1)
            presta_rows.append(["Hébergement", desc, qte, pu, f"{total_ligne:.3f}"])
        sous_total += total_ligne

    presta_data = presta_header + presta_rows
    col_widths = [largeur * 0.15, largeur * 0.42, largeur * 0.08,
                  largeur * 0.17, largeur * 0.18]

    presta_table = Table(presta_data, colWidths=col_widths)
    presta_table.setStyle(TableStyle([
        # Header
        ("BACKGROUND",   (0, 0), (-1, 0), BLEU_AGENCE),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0), 9),
        ("ALIGN",        (0, 0), (-1, 0), "CENTER"),
        # Corps
        ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",     (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS_LEGER]),
        ("ALIGN",        (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("GRID",         (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
    ]))
    elements.append(presta_table)
    elements.append(Spacer(1, 0.4 * cm))

    # ══════════════════════════════════════════════════════
    #  RÉCAPITULATIF MONTANTS
    # ══════════════════════════════════════════════════════
    recap_data = [
        ["", "Sous-total HT", f"{total_ttc:.3f} TND"],
        ["", "TVA (19%)",     f"{total_ttc * 0.19:.3f} TND"],
        ["", "TOTAL TTC",     f"{total_ttc:.3f} TND"],
    ]

    recap_table = Table(recap_data, colWidths=[largeur * 0.55, largeur * 0.25, largeur * 0.20])
    recap_table.setStyle(TableStyle([
        ("FONTNAME",     (1, 0), (1, -1), "Helvetica"),
        ("FONTNAME",     (2, 0), (2, -1), "Helvetica"),
        ("FONTNAME",     (1, 2), (2, 2), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, -1), 9),
        ("FONTSIZE",     (1, 2), (2, 2), 11),
        ("TEXTCOLOR",    (1, 2), (2, 2), VERT_TOTAL),
        ("ALIGN",        (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LINEABOVE",    (1, 2), (2, 2), 1.5, VERT_TOTAL),
        ("BACKGROUND",   (1, 2), (2, 2), colors.HexColor("#EAFAF1")),
    ]))
    elements.append(recap_table)
    elements.append(Spacer(1, 0.8 * cm))

    # ══════════════════════════════════════════════════════
    #  PIED DE PAGE
    # ══════════════════════════════════════════════════════
    elements.append(HRFlowable(width="100%", thickness=0.5, color=GRIS_TEXTE))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(Paragraph(
        f"{agence_nom} — {agence_adresse} — {agence_email} — {agence_tel}",
        styles["PiedPage"]
    ))
    elements.append(Paragraph(
        "Ce document tient lieu de facture. Merci pour votre confiance.",
        styles["PiedPage"]
    ))

    doc.build(elements)
    return buffer.getvalue()