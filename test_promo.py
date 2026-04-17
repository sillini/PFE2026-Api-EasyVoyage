import json
from easyvoyage_mcp.tools.admin_promotions import admin_promotions_liste

print("=== TOUTES les promotions (sans filtre) ===")
r = json.loads(admin_promotions_liste())
print(f"ok={r.get('ok')} total={r.get('total')}")
print(f"nb_pending={r.get('nb_pending')} nb_approved={r.get('nb_approved')} nb_rejected={r.get('nb_rejected')}")
print("error:", r.get('error'))
if r.get('data'):
    for p in r['data']:
        print(f"  {p.get('titre'):15s} statut={p.get('statut'):10s} hotel={p.get('hotel_nom')}")

print("\n=== Filtre statut=APPROVED ===")
r2 = json.loads(admin_promotions_liste(statut="APPROVED"))
print(f"total={r2.get('total')} error={r2.get('error')}")

print("\n=== Filtre statut=PENDING ===")
r3 = json.loads(admin_promotions_liste(statut="PENDING"))
print(f"total={r3.get('total')} error={r3.get('error')}")