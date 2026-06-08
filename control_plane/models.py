"""SQLAlchemy ORM models for the Control Plane."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    flow_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    boot_token_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    channel_bindings: Mapped[list["ChannelBinding"]] = relationship(back_populates="tenant")
    credentials: Mapped[list["TenantCredential"]] = relationship(back_populates="tenant")
    connector_bindings: Mapped[list["ConnectorBinding"]] = relationship(back_populates="tenant")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="tenant")


class ChannelBinding(Base):
    __tablename__ = "channel_bindings"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"))
    channel_type: Mapped[str] = mapped_column(Text)
    channel_identifier: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tenant: Mapped["Tenant"] = relationship(back_populates="channel_bindings")


class TenantCredential(Base):
    __tablename__ = "tenant_credentials"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"))
    credential_type: Mapped[str] = mapped_column(Text)
    encrypted_payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "credential_type"),)

    tenant: Mapped["Tenant"] = relationship(back_populates="credentials")


class ConnectorBinding(Base):
    __tablename__ = "connector_bindings"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"))
    category: Mapped[str] = mapped_column(Text)
    adapter_type: Mapped[str] = mapped_column(Text)
    config_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "category"),)

    tenant: Mapped["Tenant"] = relationship(back_populates="connector_bindings")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"))
    channel_type: Mapped[str] = mapped_column(Text)
    channel_user_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "channel_type", "channel_user_id"),)

    tenant: Mapped["Tenant"] = relationship(back_populates="contacts")
