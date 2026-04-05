import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Empresa, UsuarioPlataforma
from backend.routers.auth import hash_password, normalize_email


class CreateCompanyRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=150)
    cnpj_cpf: str = Field(..., min_length=11, max_length=18)
    owner_name: str = Field(..., min_length=1, max_length=150)
    owner_email: EmailStr
    password: str = Field(..., min_length=6, max_length=255)
    confirm_password: str = Field(..., min_length=6, max_length=255)


class CreateCompanyResponse(BaseModel):
    success: bool
    message: str
    empresa_id: int
    user_id: int
    owner_email: EmailStr


router = APIRouter(prefix="/api/empresas", tags=["Empresas"])


def normalize_document(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def is_repeated_digits(value: str) -> bool:
    return bool(value) and value == value[0] * len(value)


def validate_cpf(cpf: str) -> bool:
    cpf = normalize_document(cpf)

    if len(cpf) != 11 or is_repeated_digits(cpf):
        return False

    total = sum(int(cpf[i]) * (10 - i) for i in range(9))
    digit = (total * 10) % 11
    digit = 0 if digit == 10 else digit
    if digit != int(cpf[9]):
        return False

    total = sum(int(cpf[i]) * (11 - i) for i in range(10))
    digit = (total * 10) % 11
    digit = 0 if digit == 10 else digit
    return digit == int(cpf[10])


def validate_cnpj(cnpj: str) -> bool:
    cnpj = normalize_document(cnpj)

    if len(cnpj) != 14 or is_repeated_digits(cnpj):
        return False

    weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights2 = [6] + weights1

    total = sum(int(cnpj[i]) * weights1[i] for i in range(12))
    remainder = total % 11
    digit1 = 0 if remainder < 2 else 11 - remainder
    if digit1 != int(cnpj[12]):
        return False

    total = sum(int(cnpj[i]) * weights2[i] for i in range(13))
    remainder = total % 11
    digit2 = 0 if remainder < 2 else 11 - remainder
    return digit2 == int(cnpj[13])


def validate_document(value: str) -> bool:
    doc = normalize_document(value)
    if len(doc) == 11:
        return validate_cpf(doc)
    if len(doc) == 14:
        return validate_cnpj(doc)
    return False


def normalize_company_name(value: str) -> str:
    text = unicodedata.normalize("NFC", value or "")
    return text.strip()[:150]


@router.post("/criar", response_model=CreateCompanyResponse, status_code=status.HTTP_201_CREATED)
def criar_empresa(data: CreateCompanyRequest, db: Session = Depends(get_db)):
    company_name = normalize_company_name(data.company_name)
    cnpj_cpf = normalize_document(data.cnpj_cpf)

    owner_name = (data.owner_name or "").strip()
    owner_email = normalize_email(data.owner_email)
    password = data.password or ""
    confirm_password = data.confirm_password or ""

    if not company_name:
        raise HTTPException(status_code=400, detail="Nome da empresa é obrigatório.")

    if not cnpj_cpf:
        raise HTTPException(status_code=400, detail="CPF ou CNPJ é obrigatório.")

    if not validate_document(cnpj_cpf):
        raise HTTPException(status_code=400, detail="CPF ou CNPJ inválido.")

    if not owner_name:
        raise HTTPException(status_code=400, detail="Seu nome é obrigatório.")

    if not owner_email:
        raise HTTPException(status_code=400, detail="Seu e-mail é obrigatório.")

    if len(password) < 6:
        raise HTTPException(status_code=400, detail="A senha deve ter pelo menos 6 caracteres.")

    if password != confirm_password:
        raise HTTPException(status_code=400, detail="As senhas não coincidem.")

    empresa_exists = db.query(Empresa).filter(Empresa.cnpj_cpf == cnpj_cpf).first()
    if empresa_exists:
        raise HTTPException(status_code=409, detail="Já existe uma empresa com esse CPF/CNPJ.")

    owner_exists = (
        db.query(UsuarioPlataforma)
        .filter(UsuarioPlataforma.email == owner_email)
        .first()
    )
    if owner_exists:
        raise HTTPException(status_code=409, detail="Já existe um usuário com esse e-mail.")

    try:
        empresa = Empresa(
            name=company_name,
            cnpj_cpf=cnpj_cpf,
            status="active",
        )
        db.add(empresa)
        db.flush()

        usuario = UsuarioPlataforma(
            empresa_id=empresa.id,
            name=owner_name,
            email=owner_email,
            password_hash=hash_password(password),
            is_owner=True,
            is_active=True,
        )
        db.add(usuario)
        db.flush()

        db.commit()

        return CreateCompanyResponse(
            success=True,
            message=(
                "Empresa criada com sucesso. Agora entre com seu e-mail de acesso. "
                "O domínio poderá ser cadastrado depois, dentro do sistema."
            ),
            empresa_id=empresa.id,
            user_id=usuario.id,
            owner_email=owner_email,
        )

    except HTTPException:
        db.rollback()
        raise

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Já existe uma empresa ou usuário com esses dados.",
        )

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao criar empresa: {str(exc)}",
        )