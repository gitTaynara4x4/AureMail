from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Dominio, Empresa, UsuarioPlataforma
from backend.routers.auth import (
    normalize_email,
    verify_password,
    set_login_cookie,
    clear_login_cookie,
    get_current_user,
)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=255)
    remember: bool = False


class LoginResponse(BaseModel):
    success: bool
    message: str
    email: Optional[EmailStr] = None
    display_name: Optional[str] = None
    domain: Optional[str] = None
    company_name: Optional[str] = None


router = APIRouter(prefix="/api", tags=["Auth"])


def get_primary_domain(db: Session, empresa_id: int) -> str | None:
    primary = (
        db.query(Dominio)
        .filter(
            Dominio.empresa_id == empresa_id,
            Dominio.is_primary.is_(True),
        )
        .first()
    )
    if primary:
        return primary.name

    fallback = (
        db.query(Dominio)
        .filter(Dominio.empresa_id == empresa_id)
        .first()
    )
    return fallback.name if fallback else None


def get_company(db: Session, empresa_id: int) -> Empresa | None:
    return (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id)
        .first()
    )


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(data.email)
    password = data.password or ""

    user = (
        db.query(UsuarioPlataforma)
        .filter(UsuarioPlataforma.email == email)
        .first()
    )

    if not user:
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Conta inativa.")

    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")

    empresa = get_company(db, user.empresa_id)
    if not empresa:
        raise HTTPException(status_code=401, detail="Empresa vinculada não encontrada.")

    if (empresa.status or "").lower() != "active":
        raise HTTPException(status_code=403, detail="A empresa está inativa.")

    set_login_cookie(response, user, remember=data.remember)

    domain = get_primary_domain(db, user.empresa_id)

    return LoginResponse(
        success=True,
        message="Login realizado com sucesso.",
        email=user.email,
        display_name=user.name,
        domain=domain,
        company_name=empresa.name,
    )


@router.post("/logout")
def logout(response: Response):
    clear_login_cookie(response)
    return {"success": True, "message": "Logout realizado com sucesso."}


@router.get("/me")
def me(
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    empresa = get_company(db, current_user.empresa_id)
    domain = get_primary_domain(db, current_user.empresa_id)

    return {
        "success": True,
        "user": {
            "id": current_user.id,
            "empresa_id": current_user.empresa_id,
            "name": current_user.name,
            "email": current_user.email,
            "is_owner": bool(current_user.is_owner),
            "is_active": bool(current_user.is_active),
        },
        "company": {
            "id": empresa.id if empresa else None,
            "name": empresa.name if empresa else None,
            "status": empresa.status if empresa else None,
            "cnpj_cpf": empresa.cnpj_cpf if empresa else None,
        },
        "mailbox": {
            "id": current_user.id,
            "empresa_id": current_user.empresa_id,
            "dominio_id": None,
            "email": current_user.email,
            "display_name": current_user.name,
            "local_part": (
                current_user.email.split("@", 1)[0]
                if "@" in current_user.email
                else current_user.email
            ),
            "quota_mb": None,
            "is_admin": bool(current_user.is_owner),
            "is_active": bool(current_user.is_active),
            "domain": domain,
            "account_type": "platform_user",
        },
    }


@router.get("/auth/check")
def auth_check(
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    empresa = get_company(db, current_user.empresa_id)
    domain = get_primary_domain(db, current_user.empresa_id)

    return {
        "authenticated": True,
        "email": current_user.email,
        "display_name": current_user.name,
        "domain": domain,
        "company_name": empresa.name if empresa else None,
        "company_status": empresa.status if empresa else None,
        "account_type": "platform_user",
    }