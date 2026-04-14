from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
    func,
    text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Empresa(Base):
    __tablename__ = "empresas"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False)
    cnpj_cpf = Column(String(14), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, server_default=text("'active'"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    usuarios_plataforma = relationship(
        "UsuarioPlataforma",
        back_populates="empresa",
        cascade="all, delete-orphan",
    )
    dominios = relationship(
        "Dominio",
        back_populates="empresa",
        cascade="all, delete-orphan",
    )
    caixas_email = relationship(
        "CaixaEmail",
        back_populates="empresa",
        cascade="all, delete-orphan",
    )
    mensagens = relationship(
        "Mensagem",
        back_populates="empresa",
        cascade="all, delete-orphan",
    )


class UsuarioPlataforma(Base):
    __tablename__ = "usuarios_plataforma"
    __table_args__ = (
        Index("ix_usuarios_plataforma_empresa_id", "empresa_id"),
        Index("ix_usuarios_plataforma_email", "email"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    empresa_id = Column(BigInteger, ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(150), nullable=False)
    email = Column(String(320), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)

    is_owner = Column(Boolean, nullable=False, server_default=text("true"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    empresa = relationship("Empresa", back_populates="usuarios_plataforma")


class Dominio(Base):
    __tablename__ = "dominios"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    empresa_id = Column(BigInteger, ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(255), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, server_default=text("'pending'"))
    is_primary = Column(Boolean, nullable=False, server_default=text("false"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    empresa = relationship("Empresa", back_populates="dominios")
    caixas_email = relationship(
        "CaixaEmail",
        back_populates="dominio",
        cascade="all, delete-orphan",
    )


class CaixaEmail(Base):
    __tablename__ = "caixas_email"
    __table_args__ = (
        UniqueConstraint("dominio_id", "local_part", name="uq_caixas_email_dominio_local_part"),
        Index("ix_caixas_email_empresa_id", "empresa_id"),
        Index("ix_caixas_email_dominio_id", "dominio_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    empresa_id = Column(BigInteger, ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False)
    dominio_id = Column(BigInteger, ForeignKey("dominios.id", ondelete="CASCADE"), nullable=False)

    local_part = Column(String(120), nullable=False)
    email = Column(String(320), nullable=False, unique=True, index=True)

    display_name = Column(String(150), nullable=True)
    password_hash = Column(String(255), nullable=False)

    # Mantido assim por compatibilidade com o restante do projeto.
    smtp_password_enc = Column(Text, nullable=True)

    quota_mb = Column(Integer, nullable=False, server_default=text("2048"))
    is_admin = Column(Boolean, nullable=False, server_default=text("false"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    empresa = relationship("Empresa", back_populates="caixas_email")
    dominio = relationship("Dominio", back_populates="caixas_email")
    pastas = relationship(
        "Pasta",
        back_populates="caixa_email",
        cascade="all, delete-orphan",
    )
    caixa_mensagens = relationship(
        "CaixaMensagem",
        back_populates="caixa_email",
        cascade="all, delete-orphan",
    )


class Pasta(Base):
    __tablename__ = "pastas"
    __table_args__ = (
        UniqueConstraint("caixa_email_id", "slug", name="uq_pastas_caixa_email_slug"),
        Index("ix_pastas_caixa_email_id", "caixa_email_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    caixa_email_id = Column(
        BigInteger,
        ForeignKey("caixas_email.id", ondelete="CASCADE"),
        nullable=False,
    )

    name = Column(String(100), nullable=False)
    slug = Column(String(50), nullable=False)
    system_flag = Column(Boolean, nullable=False, server_default=text("true"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    caixa_email = relationship("CaixaEmail", back_populates="pastas")
    caixa_mensagens = relationship(
        "CaixaMensagem",
        back_populates="pasta",
        cascade="all, delete-orphan",
    )


class Mensagem(Base):
    __tablename__ = "mensagens"
    __table_args__ = (
        Index("ix_mensagens_empresa_id", "empresa_id"),
        Index("ix_mensagens_created_at", "created_at"),
        Index("ix_mensagens_direction", "direction"),
        Index("ix_mensagens_category", "category"),
        Index("ix_mensagens_schedule_status", "schedule_status"),
        Index("ix_mensagens_scheduled_for", "scheduled_for"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    empresa_id = Column(BigInteger, ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False)

    direction = Column(String(20), nullable=False, server_default=text("'inbound'"))
    message_id_header = Column(String(255), nullable=True, index=True)

    from_name = Column(String(150), nullable=True)
    from_email = Column(String(320), nullable=False)
    to_email = Column(String(320), nullable=False)
    cc_email = Column(Text, nullable=True)

    subject = Column(String(255), nullable=True)
    preview = Column(String(500), nullable=True)

    body_text = Column(Text, nullable=True)
    body_html = Column(Text, nullable=True)
    raw_source = Column(Text, nullable=True)

    sent_at = Column(DateTime(timezone=True), nullable=True)

    # Apoio para visões estilo Gmail
    category = Column(String(20), nullable=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    schedule_status = Column(String(20), nullable=False, server_default=text("'none'"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    empresa = relationship("Empresa", back_populates="mensagens")
    caixa_links = relationship(
        "CaixaMensagem",
        back_populates="mensagem",
        cascade="all, delete-orphan",
    )


class CaixaMensagem(Base):
    __tablename__ = "caixa_mensagens"
    __table_args__ = (
        UniqueConstraint(
            "caixa_email_id",
            "mensagem_id",
            name="uq_caixa_mensagens_caixa_email_mensagem",
        ),
        Index("ix_caixa_mensagens_caixa_email_id", "caixa_email_id"),
        Index("ix_caixa_mensagens_pasta_id", "pasta_id"),
        Index("ix_caixa_mensagens_is_read", "is_read"),
        Index("ix_caixa_mensagens_is_starred", "is_starred"),
        Index("ix_caixa_mensagens_is_important", "is_important"),
        Index("ix_caixa_mensagens_snoozed_until", "snoozed_until"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    caixa_email_id = Column(
        BigInteger,
        ForeignKey("caixas_email.id", ondelete="CASCADE"),
        nullable=False,
    )
    mensagem_id = Column(
        BigInteger,
        ForeignKey("mensagens.id", ondelete="CASCADE"),
        nullable=False,
    )
    pasta_id = Column(
        BigInteger,
        ForeignKey("pastas.id", ondelete="CASCADE"),
        nullable=False,
    )

    is_read = Column(Boolean, nullable=False, server_default=text("false"))
    is_starred = Column(Boolean, nullable=False, server_default=text("false"))
    is_important = Column(Boolean, nullable=False, server_default=text("false"))
    snoozed_until = Column(DateTime(timezone=True), nullable=True)
    is_deleted = Column(Boolean, nullable=False, server_default=text("false"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    caixa_email = relationship("CaixaEmail", back_populates="caixa_mensagens")
    mensagem = relationship("Mensagem", back_populates="caixa_links")
    pasta = relationship("Pasta", back_populates="caixa_mensagens")