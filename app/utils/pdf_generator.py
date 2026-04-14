"""
Générateur de factures PDF avec ReportLab.

Contenu :
  - En-tête : nom de l'agence + titre FACTURE + numéro
  - Informations client
  - Détail des prestations (voyage ou chambres)
  - Tableau récapitulatif fiscal dynamique (HT + taxe séjour + TVA + timbre + TTC)
  - Pied de page : mentions légales

Nouveauté module fiscal :
  generer_facture_pdf() accepte désormais des paramètres fiscaux optionnels.
  Si absents (anciennes factures), fallback sur calcul TVA 7% depuis total_ttc.
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
BLEU_AGENCE   = colors.HexColor("#1B4F72")
BLEU_CLAIR    = colors.HexColor("#D6EAF8")
GRIS_LEGER    = colors.HexColor("#F2F3F4")
GRIS_TEXTE    = colors.HexColor("#555555")
VERT_TOTAL    = colors.HexColor("#1E8449")
ORANGE_TAXE   = colors.HexColor("#E67E22")


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
        name="CellText",
        fontSize=9, fontName="Helvetica",
        textColor=colors.black,
        leading=12,
    ))
    styles.add(ParagraphStyle(
        name="PiedPage",
        fontSize=7.5, fontName="Helvetica",
        textColor=GRIS_TEXTE, alignment=1,
    ))
    return styles


def generer_facture_pdf(
    *,
    # ── Facture ───────────────────────────────────────────
    numero_facture:   str,
    date_emission:    datetime,
    statut_facture:   str,
    # ── Client ────────────────────────────────────────────
    client_nom:       str,
    client_prenom:    str,
    client_email:     str,
    client_telephone: Optional[str],
    # ── Réservation ───────────────────────────────────────
    date_debut:       str,
    date_fin:         str,
    nb_nuits:         int,
    # ── Prestations ───────────────────────────────────────
    # Pour voyage  : [{"type": "voyage", "titre": "...", "destination": "...", "prix": 1200.00}]
    # Pour chambres: [{"type": "chambre", "description": "...", "nb_nuits": 7, "prix_unitaire": 150.0, "quantite": 1}]
    prestations:      list[dict],
    # ── Montants ──────────────────────────────────────────
    total_ttc:        float,
    # ── Détail fiscal optionnel ───────────────────────────
    # Si None → fallback sur calcul TVA 7% depuis total_ttc (rétrocompatibilité)
    montant_ht:        Optional[float] = None,
    taxe_sejour:       Optional[float] = None,
    nb_nuits_taxables: Optional[int]   = None,
    taux_tva:          Optional[float] = None,
    tva_montant:       Optional[float] = None,
    droit_timbre:      Optional[float] = None,
    # ── Agence ────────────────────────────────────────────
    agence_nom:     str = "Voyage Hôtel",
    agence_slogan:  str = "Votre partenaire de voyage de confiance",
    agence_adresse: str = "Tunis, Tunisie",
    agence_email:   str = "contact@voyagehotel.com",
    agence_tel:     str = "+216 XX XXX XXX",
) -> bytes:
    """
    Génère la facture PDF et retourne les bytes.

    Si les paramètres fiscaux (montant_ht, taux_tva, etc.) sont fournis,
    le récapitulatif affiche le détail complet :
      Montant HT → Taxe de séjour → TVA → Droit de timbre → TOTAL TTC

    Sinon (anciennes factures), fallback sur le calcul : TVA = total_ttc / 1.07
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

    styles  = _get_styles()
    elements = []
    largeur  = doc.width

    # ══════════════════════════════════════════════════════
    #  EN-TÊTE : Agence (gauche) + FACTURE (droite)
    # ══════════════════════════════════════════════════════
    entete_data = [[
        [
            Paragraph(agence_nom, styles["AgenceNom"]),
            Paragraph(agence_slogan, styles["AgenceSlogan"]),
            Spacer(1, 4),
            Paragraph(agence_adresse, styles["AgenceSlogan"]),
            Paragraph(agence_email, styles["AgenceSlogan"]),
            Paragraph(agence_tel, styles["AgenceSlogan"]),
        ],
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
        ("FONTNAME",       (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",       (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",      (0, 0), (0, -1), GRIS_TEXTE),
        ("TEXTCOLOR",      (1, 0), (1, -1), colors.black),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, GRIS_LEGER]),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
        ("LEFTPADDING",    (0, 0), (-1, -1), 8),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
    ]))
    elements.append(client_table)
    elements.append(Spacer(1, 0.5 * cm))

    # ══════════════════════════════════════════════════════
    #  DÉTAIL DES PRESTATIONS
    # ══════════════════════════════════════════════════════
    elements.append(Paragraph("Détail des prestations", styles["SectionTitre"]))

    presta_header = [["Prestation", "Description", "Qté", "P.U. (DT)", "Total (DT)"]]
    presta_rows   = []

    for p in prestations:
        if p["type"] == "voyage":
            prix_ht    = p["prix"] / 1.07  # fallback pour les voyages sans détail fiscal
            desc_para  = Paragraph(
                f"{p['titre']}<br/>"
                f"<font size='8' color='#777777'>Destination : {p['destination']}</font>",
                styles["CellText"]
            )
            presta_rows.append([
                "Voyage", desc_para, "1",
                f"{prix_ht:.3f}", f"{prix_ht:.3f}",
            ])
        else:
            prix_ht_nuit = p.get("prix_unitaire", 0)
            quantite     = p.get("quantite", 1)
            desc_text    = p.get("description") or "Hébergement"
            desc_para    = Paragraph(desc_text, styles["CellText"])
            total_ligne  = prix_ht_nuit * quantite
            presta_rows.append([
                "Hébergement", desc_para, str(quantite),
                f"{prix_ht_nuit:.3f}", f"{total_ligne:.3f}",
            ])

    presta_data = presta_header + presta_rows
    col_widths  = [
        largeur * 0.14, largeur * 0.44, largeur * 0.07,
        largeur * 0.17, largeur * 0.18,
    ]

    presta_table = Table(presta_data, colWidths=col_widths)
    presta_table.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0), BLEU_AGENCE),
        ("TEXTCOLOR",      (0, 0), (-1, 0), colors.white),
        ("FONTNAME",       (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, 0), 9),
        ("ALIGN",          (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME",       (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",       (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS_LEGER]),
        ("ALIGN",          (2, 1), (-1, -1), "RIGHT"),
        ("ALIGN",          (0, 1), (0, -1), "LEFT"),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 7),
        ("LEFTPADDING",    (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 8),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
    ]))
    elements.append(presta_table)
    elements.append(Spacer(1, 0.4 * cm))

    # ══════════════════════════════════════════════════════
    #  RÉCAPITULATIF FISCAL DYNAMIQUE
    #
    #  Si les paramètres fiscaux sont fournis (nouvelles factures) :
    #    Montant HT → Taxe de séjour → TVA → Droit de timbre → TOTAL TTC
    #
    #  Sinon (anciennes factures sans détail fiscal) :
    #    Fallback : calcul TVA 7% depuis total_ttc
    # ══════════════════════════════════════════════════════

    # ── Résolution des valeurs fiscales ──────────────────
    if montant_ht is None:
        # Fallback rétrocompatibilité : recalcul depuis total_ttc
        _taux       = taux_tva if taux_tva else 7.0
        _montant_ht = round(total_ttc / (1 + _taux / 100), 3)
        _tva        = round(total_ttc - _montant_ht, 3)
        _taxe       = 0.0
        _timbre     = 0.0
        _nb_tax     = 0
        _taux_use   = _taux
    else:
        _montant_ht = montant_ht
        _tva        = tva_montant or 0.0
        _taxe       = taxe_sejour or 0.0
        _timbre     = droit_timbre or 0.0
        _nb_tax     = nb_nuits_taxables or 0
        _taux_use   = taux_tva or 7.0

    # ── Construction dynamique des lignes ─────────────────
    recap_data = [["", "Montant HT", f"{_montant_ht:.3f} DT"]]

    # Taxe de séjour (uniquement si > 0)
    if _taxe > 0:
        nuits_label = f"{_nb_tax} nuit{'s' if _nb_tax > 1 else ''} taxée{'s' if _nb_tax > 1 else ''}"
        recap_data.append(["", f"Taxe de séjour ({nuits_label})", f"{_taxe:.3f} DT"])

    # TVA
    recap_data.append(["", f"TVA ({_taux_use:.0f}%)", f"{_tva:.3f} DT"])

    # Droit de timbre (uniquement si > 0)
    if _timbre > 0:
        recap_data.append(["", "Droit de timbre", f"{_timbre:.3f} DT"])

    # Total TTC — toujours en dernière ligne
    recap_data.append(["", "TOTAL TTC", f"{total_ttc:.3f} DT"])

    idx_total = len(recap_data) - 1   # index de la ligne TOTAL TTC
    idx_taxe  = 1 if _taxe > 0 else None  # index de la ligne taxe séjour (si présente)

    # ── Styles du tableau récapitulatif ───────────────────
    recap_style = [
        ("FONTNAME",      (1, 0), (1, -1), "Helvetica"),
        ("FONTNAME",      (2, 0), (2, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        # Ligne TOTAL TTC mise en évidence
        ("FONTNAME",      (1, idx_total), (2, idx_total), "Helvetica-Bold"),
        ("FONTSIZE",      (1, idx_total), (2, idx_total), 11),
        ("TEXTCOLOR",     (1, idx_total), (2, idx_total), VERT_TOTAL),
        ("LINEABOVE",     (1, idx_total), (2, idx_total), 1.5, VERT_TOTAL),
        ("BACKGROUND",    (1, idx_total), (2, idx_total), colors.HexColor("#EAFAF1")),
    ]
    # Colorer la ligne taxe séjour en orange si présente
    if idx_taxe is not None:
        recap_style += [
            ("TEXTCOLOR", (1, idx_taxe), (2, idx_taxe), ORANGE_TAXE),
        ]

    recap_table = Table(
        recap_data,
        colWidths=[largeur * 0.50, largeur * 0.30, largeur * 0.20]
    )
    recap_table.setStyle(TableStyle(recap_style))
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


def generer_facture_paiement_partenaire(
    *,
    numero_facture:    str,
    date_paiement:     datetime,
    partenaire_nom:    str,
    partenaire_prenom: str,
    partenaire_email:  str,
    partenaire_tel:    str = "—",
    nom_entreprise:    str = "—",
    montant:           float,
    note:              str = "",
    agence_nom:     str = "EasyVoyage",
    agence_slogan:  str = "Votre partenaire de voyage de confiance",
    agence_adresse: str = "Tunis, Tunisie",
    agence_email:   str = "contact@easyvoyage.com",
    agence_tel:     str = "+216 XX XXX XXX",
) -> bytes:
    """Génère la facture PDF d'un paiement partenaire et retourne les bytes."""

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm,  bottomMargin=2 * cm,
        title=f"Facture {numero_facture}",
        author=agence_nom,
    )

    styles   = _get_styles()
    elements = []
    largeur  = doc.width

    # ── En-tête ───────────────────────────────────────────
    entete_data = [[
        [
            Paragraph(agence_nom,     styles["AgenceNom"]),
            Paragraph(agence_slogan,  styles["AgenceSlogan"]),
            Spacer(1, 4),
            Paragraph(agence_adresse, styles["AgenceSlogan"]),
            Paragraph(agence_email,   styles["AgenceSlogan"]),
            Paragraph(agence_tel,     styles["AgenceSlogan"]),
        ],
        [
            Paragraph("REÇU DE PAIEMENT", styles["TitreFacture"]),
            Paragraph(f"N° <b>{numero_facture}</b>", styles["NumeroFacture"]),
            Spacer(1, 6),
            Paragraph(
                f"Date : <b>{date_paiement.strftime('%d/%m/%Y')}</b>",
                styles["InfoValue"]
            ),
            Paragraph("Statut : <b>PAYÉ</b>", styles["InfoValue"]),
        ],
    ]]
    entete_table = Table(entete_data, colWidths=[largeur * 0.55, largeur * 0.45])
    entete_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN",  (1, 0), (1, 0),   "RIGHT"),
    ]))
    elements.append(entete_table)
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(HRFlowable(width="100%", thickness=2, color=BLEU_AGENCE))
    elements.append(Spacer(1, 0.4 * cm))

    # ── Informations partenaire ───────────────────────────
    elements.append(Paragraph("Bénéficiaire", styles["SectionTitre"]))
    part_data = [
        ["Nom complet",  f"{partenaire_prenom} {partenaire_nom}"],
        ["Email",        partenaire_email],
        ["Téléphone",    partenaire_tel],
        ["Entreprise",   nom_entreprise],
    ]
    part_table = Table(part_data, colWidths=[largeur * 0.25, largeur * 0.75])
    part_table.setStyle(TableStyle([
        ("FONTNAME",       (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",       (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",      (0, 0), (0, -1), GRIS_TEXTE),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, GRIS_LEGER]),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
        ("LEFTPADDING",    (0, 0), (-1, -1), 8),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
    ]))
    elements.append(part_table)
    elements.append(Spacer(1, 0.5 * cm))

    # ── Détail du paiement ────────────────────────────────
    elements.append(Paragraph("Détail du paiement", styles["SectionTitre"]))
    presta_header = [["Description", "Montant (DT)"]]
    presta_rows   = [["Virement partenaire — commission sur réservations hôtelières",
                       f"{montant:.2f}"]]
    if note:
        presta_rows.append([f"Note : {note}", ""])

    presta_data = presta_header + presta_rows
    presta_table = Table(presta_data, colWidths=[largeur * 0.75, largeur * 0.25])
    presta_table.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  BLEU_AGENCE),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",       (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("ALIGN",          (1, 0), (1, -1),  "RIGHT"),
        ("FONTNAME",       (0, 1), (-1, -1), "Helvetica"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS_LEGER]),
        ("TOPPADDING",     (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 7),
        ("LEFTPADDING",    (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 8),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
    ]))
    elements.append(presta_table)
    elements.append(Spacer(1, 0.5 * cm))

    # ── Total ─────────────────────────────────────────────
    recap_data = [["", "TOTAL VERSÉ", f"{montant:.2f} DT"]]
    recap_table = Table(recap_data, colWidths=[largeur * 0.55, largeur * 0.25, largeur * 0.20])
    recap_table.setStyle(TableStyle([
        ("FONTNAME",      (1, 0), (2, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (1, 0), (2, 0), 12),
        ("TEXTCOLOR",     (1, 0), (2, 0), VERT_TOTAL),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEABOVE",     (1, 0), (2, 0), 1.5, VERT_TOTAL),
        ("BACKGROUND",    (1, 0), (2, 0), colors.HexColor("#EAFAF1")),
    ]))
    elements.append(recap_table)
    elements.append(Spacer(1, 1 * cm))

    # ── Pied de page ──────────────────────────────────────
    elements.append(HRFlowable(width="100%", thickness=0.5, color=GRIS_TEXTE))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(Paragraph(
        f"{agence_nom} — {agence_adresse} — {agence_email} — {agence_tel}",
        styles["PiedPage"]
    ))
    elements.append(Paragraph(
        "Ce document tient lieu de reçu de paiement officiel. Merci pour votre confiance.",
        styles["PiedPage"]
    ))

    doc.build(elements)
    return buffer.getvalue()