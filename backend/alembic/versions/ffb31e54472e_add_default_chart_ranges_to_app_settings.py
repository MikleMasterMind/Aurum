"""add default chart ranges to app_settings

Revision ID: ffb31e54472e
Revises: d1a6f4c8b729
Create Date: 2026-11-21 20:35:03.929442

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ffb31e54472e'
down_revision: Union[str, None] = 'd1a6f4c8b729'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default while adding: the row already exists (id=1), so a
    # NOT NULL column needs a value to backfill it with — dropped right
    # after, same pattern as b4e7c1a9f203. New rows are covered by the ORM
    # defaults in models/settings.py.
    # Note: autogenerate also wanted to drop ix_categories_parent_id here —
    # a long-standing model/DB mismatch unrelated to this change (the index
    # exists in the DB, the model just never declared it), so it stays.
    op.add_column(
        'app_settings',
        sa.Column('default_net_worth_range', sa.String(length=10), nullable=False, server_default='5y'),
    )
    op.add_column(
        'app_settings',
        sa.Column('default_cash_flow_range', sa.String(length=10), nullable=False, server_default='this_year'),
    )
    op.add_column(
        'app_settings',
        sa.Column('default_reports_range', sa.String(length=10), nullable=False, server_default='all'),
    )
    op.add_column(
        'app_settings',
        sa.Column('default_crypto_range', sa.String(length=8), nullable=False, server_default='all'),
    )
    op.alter_column('app_settings', 'default_net_worth_range', server_default=None)
    op.alter_column('app_settings', 'default_cash_flow_range', server_default=None)
    op.alter_column('app_settings', 'default_reports_range', server_default=None)
    op.alter_column('app_settings', 'default_crypto_range', server_default=None)


def downgrade() -> None:
    op.drop_column('app_settings', 'default_crypto_range')
    op.drop_column('app_settings', 'default_reports_range')
    op.drop_column('app_settings', 'default_cash_flow_range')
    op.drop_column('app_settings', 'default_net_worth_range')
