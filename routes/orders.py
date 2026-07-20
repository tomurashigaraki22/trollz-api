import os
import requests
from flask import Blueprint, request, jsonify
from lib.db import query, query_one, execute

orders_bp = Blueprint("orders", __name__)

@orders_bp.route("", methods=["GET"])
def get_orders():
    status = request.args.get("status", "all")
    sql = """
        SELECT o.*, u.email as user_email, u.name as user_name
        FROM orders o
        LEFT JOIN users u ON o.user_id = u.id
        WHERE 1=1
    """
    params = []
    if status != "all":
        sql += " AND o.payment_status = %s"
        params.append(status)
    sql += " ORDER BY o.created_at DESC"

    rows = query(sql, params)
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = str(r["created_at"])
    return jsonify(rows)

@orders_bp.route("/<int:oid>", methods=["PATCH"])
def update_order(oid):
    data = request.get_json()
    action = data.get("action")

    if action == "update_status":
        execute("UPDATE orders SET order_status=%s WHERE id=%s", (data["status"], oid))
        return jsonify({"success": True})

    if action == "cancel":
        order = query_one("SELECT stock_restored FROM orders WHERE id=%s", (oid,))
        if order and not order["stock_restored"]:
            items = query("SELECT product_id, quantity FROM order_items WHERE order_id=%s", (oid,))
            for item in items:
                execute("UPDATE product SET qty = qty + %s WHERE id=%s",
                        (item["quantity"], item["product_id"]))
            execute("UPDATE orders SET order_status='cancelled', stock_restored=1 WHERE id=%s", (oid,))
        return jsonify({"success": True})

    if action == "refund":
        transaction_id = data.get("transaction_id")
        secret_key = os.getenv("FLUTTERWAVE_SECRET_KEY")
        resp = requests.post(
            f"https://api.flutterwave.com/v3/transactions/{transaction_id}/refund",
            headers={"Authorization": f"Bearer {secret_key}", "Content-Type": "application/json"}
        )
        fw = resp.json()
        if fw.get("status") == "success":
            execute("UPDATE orders SET payment_status='refunded', order_status='cancelled' WHERE id=%s", (oid,))
            return jsonify({"success": True})
        return jsonify({"error": "Refund failed", "detail": fw}), 400

    return jsonify({"error": "Invalid action"}), 400
