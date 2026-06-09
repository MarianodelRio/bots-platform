"""add flows and flow_versions tables; drop flow_path from tenants

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flows",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("origin_template_id", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_flows_tenant_id", "flows", ["tenant_id"])
    op.create_table(
        "flow_versions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("flow_id", sa.Text, sa.ForeignKey("flows.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("yaml_content", sa.Text, nullable=False),
        sa.Column("checksum", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_flow_versions_flow_version", "flow_versions", ["flow_id", "version"]
    )
    op.create_index(
        "uq_flow_versions_active",
        "flow_versions",
        ["flow_id"],
        unique=True,
        postgresql_where="is_active = true",
    )
    op.drop_column("tenants", "flow_path")


def downgrade() -> None:
    op.add_column("tenants", sa.Column("flow_path", sa.Text, nullable=True))
    op.drop_index("uq_flow_versions_active", table_name="flow_versions")
    op.drop_constraint("uq_flow_versions_flow_version", "flow_versions", type_="unique")
    op.drop_table("flow_versions")
    op.drop_constraint("uq_flows_tenant_id", "flows", type_="unique")
    op.drop_table("flows")
