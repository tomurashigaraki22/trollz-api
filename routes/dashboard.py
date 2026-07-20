from flask import Blueprint, jsonify
from lib.db import query_one, query

dashboard_bp = Blueprint("dashboard", __name__)

@dashboard_bp.route("", methods=["GET"])
def get_stats():
    revenue = query_one("SELECT COALESCE(SUM(total_amount),0) as total FROM orders WHERE payment_status='paid'")
    orders = query_one("SELECT COUNT(*) as count FROM orders")
    today = query_one("SELECT COALESCE(SUM(total_amount),0) as total FROM orders WHERE payment_status='paid' AND DATE(created_at)=CURDATE()")
    users = query_one("SELECT COUNT(*) as count FROM users")
    last7 = query(
        "SELECT DATE(created_at) as day, COALESCE(SUM(total_amount),0) as revenue "
        "FROM orders WHERE payment_status='paid' AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY) "
        "GROUP BY DATE(created_at) ORDER BY day ASC"
    )
    monthly = query(
        "SELECT MONTH(created_at) as month, COALESCE(SUM(total_amount),0) as revenue "
        "FROM orders WHERE payment_status='paid' AND YEAR(created_at)=YEAR(NOW()) "
        "GROUP BY MONTH(created_at) ORDER BY month ASC"
    )

    # Convert dates to strings for JSON
    for row in last7:
        if row.get("day"):
            row["day"] = str(row["day"])

    return jsonify({
        "totalRevenue": float(revenue["total"]) if revenue else 0,
        "totalOrders": orders["count"] if orders else 0,
        "todaySales": float(today["total"]) if today else 0,
        "totalUsers": users["count"] if users else 0,
        "last7Days": last7,
        "monthly": monthly,
    })
