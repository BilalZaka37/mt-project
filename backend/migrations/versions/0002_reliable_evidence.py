"""MT Project incident clips, explainable events, and durable alert deliveries."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cameras',sa.Column('provenance',sa.JSON,nullable=False,server_default='{}'))
    for column in [
        sa.Column('details', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('clip_status', sa.String(20), nullable=False, server_default='none'),
        sa.Column('clip_filename', sa.String(100), nullable=True),
        sa.Column('clip_duration', sa.Float, nullable=False, server_default='0'),
        sa.Column('clip_offset', sa.Float, nullable=False, server_default='0'),
        sa.Column('clip_truncated', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('clip_error', sa.String(200), nullable=True),
    ]:
        op.add_column('events', column)
    op.create_table('alert_endpoints',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('url', sa.String(2048), nullable=False),
        sa.Column('secret_encrypted', sa.Text, nullable=False),
        sa.Column('active', sa.Boolean, nullable=False),
        sa.Column('kinds', sa.JSON, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('alert_deliveries',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('endpoint_id', sa.Integer, sa.ForeignKey('alert_endpoints.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_id', sa.Integer, sa.ForeignKey('events.id', ondelete='SET NULL')),
        sa.Column('payload', sa.JSON, nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('attempts', sa.Integer, nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('locked_until', sa.DateTime(timezone=True)),
        sa.Column('last_error', sa.String(200)),
        sa.Column('http_status', sa.Integer),
        sa.Column('delivered_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    for col in ['endpoint_id', 'event_id', 'status', 'next_attempt_at']:
        op.create_index('ix_alert_deliveries_'+col, 'alert_deliveries', [col])


def downgrade():
    op.drop_table('alert_deliveries')
    op.drop_table('alert_endpoints')
    with op.batch_alter_table('events') as batch:
        for name in ['details','clip_status','clip_filename','clip_duration','clip_offset','clip_truncated','clip_error']:
            batch.drop_column(name)
    with op.batch_alter_table('cameras') as batch:
        batch.drop_column('provenance')
