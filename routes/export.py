import csv
import io
from flask import Blueprint, Response
from lib.db import query

export_bp = Blueprint("export", __name__)

@export_bp.route("/orders", methods=["GET"])
def export_orders():
    rows = query("""
        SELECT o.id, o.tracking, u.email as user_email, o.total_amount,
               o.payment_status, o.order_status, o.created_at
        FROM orders o
        LEFT JOIN users u ON o.user_id = u.id
        ORDER BY o.created_at DESC
    """)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Tracking", "Email", "Total", "Payment Status", "Order Status", "Date"])
    for r in rows:
        writer.writerow([
            r["id"], r.get("tracking", ""), r.get("user_email", ""),
            r["total_amount"], r["payment_status"], r["order_status"], r["created_at"]
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"}
    )
