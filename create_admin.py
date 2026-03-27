"""
Script pour créer un administrateur en base de données.
Usage :
    python create_admin.py
"""
import asyncio
import sys
import os

# Ajouter le dossier racine au path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.utilisateur import Utilisateur, Admin, RoleUtilisateur
from app.core.security import hash_password


async def create_admin(
    nom: str,
    prenom: str,
    email: str,
    password: str,
    telephone: str = None,
):
    async with AsyncSessionLocal() as session:
        # Vérifier si l'email existe déjà
        result = await session.execute(
            select(Utilisateur).where(Utilisateur.email == email)
        )
        existing = result.scalar_one_or_none()

        if existing:
            print(f"❌ Un utilisateur avec l'email '{email}' existe déjà.")
            return

        # Créer l'utilisateur
        user = Utilisateur(
            nom=nom,
            prenom=prenom,
            email=email,
            telephone=telephone,
            mot_de_passe=hash_password(password),
            role=RoleUtilisateur.ADMIN,
        )
        session.add(user)
        await session.flush()  # Récupérer l'id

        # Créer la ligne admin
        admin = Admin(id=user.id)
        session.add(admin)

        await session.commit()
        print(f"✅ Admin créé avec succès !")
        print(f"   ID    : {user.id}")
        print(f"   Nom   : {user.prenom} {user.nom}")
        print(f"   Email : {user.email}")
        print(f"   Rôle  : {user.role.value}")


if __name__ == "__main__":
    # ── Modifier ces valeurs ──────────────────────────────────
    NOM        = "Admin"
    PRENOM     = "Super"
    EMAIL      = "silliniahmed2004@gmail.com"
    PASSWORD   = "malek123"
    TELEPHONE  = "+21621719911"
    # ─────────────────────────────────────────────────────────

    asyncio.run(create_admin(
        nom=NOM,
        prenom=PRENOM,
        email=EMAIL,
        password=PASSWORD,
        telephone=TELEPHONE,
    ))