from flask import Blueprint, request, jsonify
from lib.db import query, query_one, execute

support_bp = Blueprint("support", __name__)

@support_bp.route("", methods=["GET"])
def get_tickets():
    rows = query("SELECT * FROM support_messages ORDER BY created_at DESC")
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = str(r["created_at"])
    return jsonify(rows)

@support_bp.route("/<int:tid>", methods=["GET"])
def get_ticket(tid):
    t = query_one("SELECT * FROM support_messages WHERE id=%s", (tid,))
    if not t:
        return jsonify({"error": "Not found"}), 404
    if t.get("created_at"):
        t["created_at"] = str(t["created_at"])
    return jsonify(t)

@support_bp.route("/<int:tid>", methods=["PATCH"])
def patch_ticket(tid):
    data = request.get_json()
    if data.get("action") == "resolve":
        execute("UPDATE support_messages SET status='resolved' WHERE id=%s", (tid,))
    return jsonify({"success": True})

@support_bp.route("/<int:tid>", methods=["DELETE"])
def delete_ticket(tid):
    execute("DELETE FROM support_messages WHERE id=%s", (tid,))
    return jsonify({"success": True})
