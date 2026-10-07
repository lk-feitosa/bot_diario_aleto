from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, BigInteger, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Edicao(Base):
    __tablename__ = "edicoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    numero: Mapped[str] = mapped_column(String(50), index=True)
    data_publicacao: Mapped[str] = mapped_column(String(50))
    url_download: Mapped[str] = mapped_column(String(255), unique=True)
    pdf_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    resumo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relacionamentos
    alertas: Mapped[List["Alerta"]] = relationship("Alerta", back_populates="edicao", cascade="all, delete-orphan")
    envios: Mapped[List["EdicaoEnviada"]] = relationship("EdicaoEnviada", back_populates="edicao", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Edicao(numero='{self.numero}', data='{self.data_publicacao}')>"


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ultimo_acesso: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    bloqueado_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relacionamentos
    termos: Mapped[List["TermoMonitorado"]] = relationship("TermoMonitorado", back_populates="usuario", cascade="all, delete-orphan")
    alertas: Mapped[List["Alerta"]] = relationship("Alerta", back_populates="usuario", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Usuario(chat_id={self.chat_id}, username='{self.username}', ativo={self.ativo})>"


class TermoMonitorado(Base):
    __tablename__ = "termos_monitorados"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usuario_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    termo: Mapped[str] = mapped_column(String(200), index=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relacionamento
    usuario: Mapped[Optional["Usuario"]] = relationship("Usuario", back_populates="termos")

    def __repr__(self) -> str:
        return f"<TermoMonitorado(termo='{self.termo}', usuario_id={self.usuario_id})>"


class Alerta(Base):
    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    edicao_id: Mapped[int] = mapped_column(ForeignKey("edicoes.id"))
    usuario_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id"), nullable=True, index=True)
    termo: Mapped[str] = mapped_column(String(200))
    pagina: Mapped[int] = mapped_column(Integer)
    trecho: Mapped[str] = mapped_column(Text)
    enviado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relacionamentos
    edicao: Mapped["Edicao"] = relationship("Edicao", back_populates="alertas")
    usuario: Mapped[Optional["Usuario"]] = relationship("Usuario", back_populates="alertas")

    def __repr__(self) -> str:
        return f"<Alerta(edicao_id={self.edicao_id}, termo='{self.termo}', pagina={self.pagina})>"


class InteracaoLog(Base):
    """Registra cada comando executado pelos usuários para analytics."""
    __tablename__ = "interacoes_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    comando: Mapped[str] = mapped_column(String(50))
    parametros: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    executado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self) -> str:
        return f"<InteracaoLog(chat_id={self.chat_id}, comando='{self.comando}')>"


class EdicaoEnviada(Base):
    """Registra quais edições foram entregues a cada chat_id."""
    __tablename__ = "edicoes_enviadas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    edicao_id: Mapped[int] = mapped_column(ForeignKey("edicoes.id"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    sucesso: Mapped[bool] = mapped_column(Boolean, default=True)
    enviado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relacionamento
    edicao: Mapped["Edicao"] = relationship("Edicao", back_populates="envios")

    def __repr__(self) -> str:
        return f"<EdicaoEnviada(edicao_id={self.edicao_id}, chat_id={self.chat_id}, sucesso={self.sucesso})>"
