"""Add the read-only business owner role."""
from alembic import op
import sqlalchemy as sa

revision = "0ef29846bf74"
down_revision = "67b71295a5af"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("users_role_check", "users", type_="check")
    op.create_check_constraint("ck_users_role", "users", "role in ('customer','driver','admin','owner')")


def downgrade():
    has_owner = op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM users WHERE role = 'owner')"))
    if has_owner:
        raise RuntimeError("Remove or explicitly reassign owner accounts before downgrading.")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint("users_role_check", "users", "role in ('customer','driver','admin')")
