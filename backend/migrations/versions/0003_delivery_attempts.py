"""MT Project per-attempt delivery evidence."""
from alembic import op
import sqlalchemy as sa

revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('delivery_attempts',
        sa.Column('id',sa.Integer,primary_key=True),
        sa.Column('delivery_id',sa.String(32),sa.ForeignKey('alert_deliveries.id',ondelete='CASCADE'),nullable=False),
        sa.Column('attempt_number',sa.Integer,nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('started_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('finished_at',sa.DateTime(timezone=True)),
        sa.Column('http_status',sa.Integer),
        sa.Column('error',sa.String(200)),
        sa.UniqueConstraint('delivery_id','attempt_number',name='uq_delivery_attempt_number'))
    op.create_index('ix_delivery_attempts_delivery_id','delivery_attempts',['delivery_id'])


def downgrade():
    op.drop_table('delivery_attempts')
