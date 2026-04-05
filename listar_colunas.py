from pathlib import Path
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não encontrada no .env")

print("Banco em uso:", DATABASE_URL)
print()
confirm = input(
    "ATENÇÃO: isso vai APAGAR TUDO do schema public e recriar do zero.\n"
    "Digite APAGAR TUDO para continuar: "
).strip()

if confirm != "APAGAR TUDO":
    print("Operação cancelada.")
    sys.exit(0)

engine = create_engine(DATABASE_URL, future=True)

DROP_AND_RECREATE_PUBLIC = """
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO public;
"""

CREATE_ALL = """
CREATE TABLE public.empresas (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    cnpj_cpf VARCHAR(14) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_empresas_cnpj_cpf
    ON public.empresas (cnpj_cpf);

CREATE TABLE public.usuarios_plataforma (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES public.empresas(id) ON DELETE CASCADE,
    name VARCHAR(150) NOT NULL,
    email VARCHAR(320) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    is_owner BOOLEAN NOT NULL DEFAULT TRUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_usuarios_plataforma_empresa_id
    ON public.usuarios_plataforma (empresa_id);

CREATE INDEX ix_usuarios_plataforma_email
    ON public.usuarios_plataforma (email);

CREATE TABLE public.dominios (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES public.empresas(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_dominios_name
    ON public.dominios (name);

CREATE TABLE public.caixas_email (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES public.empresas(id) ON DELETE CASCADE,
    dominio_id BIGINT NOT NULL REFERENCES public.dominios(id) ON DELETE CASCADE,
    local_part VARCHAR(120) NOT NULL,
    email VARCHAR(320) NOT NULL UNIQUE,
    display_name VARCHAR(150),
    password_hash VARCHAR(255) NOT NULL,
    quota_mb INTEGER NOT NULL DEFAULT 2048,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_caixas_email_dominio_local_part UNIQUE (dominio_id, local_part)
);

CREATE INDEX ix_caixas_email_empresa_id
    ON public.caixas_email (empresa_id);

CREATE INDEX ix_caixas_email_dominio_id
    ON public.caixas_email (dominio_id);

CREATE INDEX ix_caixas_email_email
    ON public.caixas_email (email);

CREATE TABLE public.pastas (
    id BIGSERIAL PRIMARY KEY,
    caixa_email_id BIGINT NOT NULL REFERENCES public.caixas_email(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(50) NOT NULL,
    system_flag BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_pastas_caixa_email_slug UNIQUE (caixa_email_id, slug)
);

CREATE INDEX ix_pastas_caixa_email_id
    ON public.pastas (caixa_email_id);

CREATE TABLE public.mensagens (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES public.empresas(id) ON DELETE CASCADE,
    direction VARCHAR(20) NOT NULL DEFAULT 'inbound',
    message_id_header VARCHAR(255),
    from_name VARCHAR(150),
    from_email VARCHAR(320) NOT NULL,
    to_email VARCHAR(320) NOT NULL,
    cc_email TEXT,
    subject VARCHAR(255),
    preview VARCHAR(500),
    body_text TEXT,
    body_html TEXT,
    raw_source TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_mensagens_empresa_id
    ON public.mensagens (empresa_id);

CREATE INDEX ix_mensagens_created_at
    ON public.mensagens (created_at);

CREATE INDEX ix_mensagens_direction
    ON public.mensagens (direction);

CREATE INDEX ix_mensagens_message_id_header
    ON public.mensagens (message_id_header);

CREATE TABLE public.caixa_mensagens (
    id BIGSERIAL PRIMARY KEY,
    caixa_email_id BIGINT NOT NULL REFERENCES public.caixas_email(id) ON DELETE CASCADE,
    mensagem_id BIGINT NOT NULL REFERENCES public.mensagens(id) ON DELETE CASCADE,
    pasta_id BIGINT NOT NULL REFERENCES public.pastas(id) ON DELETE CASCADE,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    is_starred BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_caixa_mensagens_caixa_email_mensagem UNIQUE (caixa_email_id, mensagem_id)
);

CREATE INDEX ix_caixa_mensagens_caixa_email_id
    ON public.caixa_mensagens (caixa_email_id);

CREATE INDEX ix_caixa_mensagens_pasta_id
    ON public.caixa_mensagens (pasta_id);

CREATE INDEX ix_caixa_mensagens_is_read
    ON public.caixa_mensagens (is_read);
"""

LIST_TABLES = """
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
"""

LIST_COLUMNS = """
SELECT table_name, ordinal_position, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
"""

with engine.connect() as conn:
    conn = conn.execution_options(isolation_level="AUTOCOMMIT")

    print("\nApagando schema public...")
    conn.execute(text(DROP_AND_RECREATE_PUBLIC))

    print("Criando estrutura nova...")
    for statement in CREATE_ALL.split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(text(stmt))

    print("\nTabelas criadas:")
    tables = conn.execute(text(LIST_TABLES)).fetchall()
    for row in tables:
        print("-", row[0])

    print("\nColunas criadas:")
    current_table = None
    cols = conn.execute(text(LIST_COLUMNS)).fetchall()
    for row in cols:
        table_name, ordinal_position, column_name, data_type = row
        if table_name != current_table:
            current_table = table_name
            print(f"\n=== {table_name} ===")
        print(f"{ordinal_position}. {column_name} | {data_type}")

print("\nBanco resetado com sucesso.")