from fastapi import HTTPException

SCOPES = {
    "operations": frozenset({"customers", "drivers", "verifications", "bookings", "live-operations", "metrics"}),
    "finance": frozenset({"bookings", "pricing", "commissions", "payments", "refunds", "payouts", "reports", "financials"}),
    "support": frozenset({"incidents", "reviews", "support", "customers", "bookings"}),
}


def permit(user, section):
    if user.role != "admin" or (user.staff_scope is not None and section not in SCOPES.get(user.staff_scope, ())):
        raise HTTPException(403, "This administrative permission is required.")


def admin_section(path):
    parts = path.rstrip("/").split("/")
    if "admin" not in parts:
        return ""
    tail = parts[parts.index("admin") + 1:]
    if tail and tail[0] == "directory":
        tail = tail[1:]
    return tail[0] if tail else ""
