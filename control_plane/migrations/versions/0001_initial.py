"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-08
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("flow_path", sa.Text, nullable=True),
        sa.Column("boot_token_hash", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "channel_bindings",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("channel_type", sa.Text, nullable=False),
        sa.Column("channel_identifier", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "tenant_credentials",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("credential_type", sa.Text, nullable=False),
        sa.Column("encrypted_payload", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("tenant_id", "credential_type"),
    )
    op.create_table(
        "connector_bindings",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("adapter_type", sa.Text, nullable=False),
        sa.Column("config_json", sa.JSON, nullable=True),
        sa.Column(
            "created_at", sa.DateTime, nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("tenant_id", "category"),
    )
    op.create_table(
        "contacts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("channel_type", sa.Text, nullable=False),
        sa.Column("channel_user_id", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("tenant_id", "channel_type", "channel_user_id"),
    )


def downgrade() -> None:
    op.drop_table("contacts")
    op.drop_table("connector_bindings")
    op.drop_table("tenant_credentials")
    op.drop_table("channel_bindings")
    op.drop_table("tenants")
