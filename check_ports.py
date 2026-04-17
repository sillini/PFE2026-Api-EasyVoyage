import inspect, json
from easyvoyage_mcp.tools.admin_promotions import admin_promotions_liste

# Vérifier le code source chargé
src = inspect.getsource(admin_promotions_liste)

print("=== VÉRIFICATION FICHIER CHARGÉ ===")
if "CAST(p.statut AS VARCHAR)" in src:
    print("✅ NOUVEAU fichier chargé — contient CAST")
else:
    print("❌ ANCIEN fichier chargé — ne contient PAS CAST")

if "hotel_nom" in src:
    print("✅ Paramètre hotel_nom présent")
else:
    print("❌ Paramètre hotel_nom ABSENT (ancien fichier)")

# Localisation du fichier
import easyvoyage_mcp.tools.admin_promotions as mod
print(f"\nFichier chargé : {mod.__file__}")

# Test appel direct
print("\n=== TEST APPEL DIRECT ===")
r = json.loads(admin_promotions_liste())
print(f"total={r.get('total')} nb_approved={r.get('nb_approved')} nb_rejected={r.get('nb_rejected')}")

r2 = json.loads(admin_promotions_liste(statut="REJECTED"))
print(f"REJECTED: total={r2.get('total')} error={r2.get('error')}")