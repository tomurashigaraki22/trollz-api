from flask import Blueprint, request, jsonify
from lib.db import query, execute

delivery_bp = Blueprint("delivery", __name__)

@delivery_bp.route("", methods=["GET"])
def get_fees():
    return jsonify(query("SELECT * FROM price ORDER BY id ASC"))

@delivery_bp.route("", methods=["POST"])
def create_fee():
    data = request.get_json()
    execute("INSERT INTO price (location, price) VALUES (%s,%s)", (data["location"], data["price"]))
    return jsonify({"success": True})

@delivery_bp.route("/<int:fid>", methods=["PUT"])
def update_fee(fid):
    data = request.get_json()
    execute("UPDATE price SET location=%s, price=%s WHERE id=%s", (data["location"], data["price"], fid))
    return jsonify({"success": True})

@delivery_bp.route("/<int:fid>", methods=["DELETE"])
def delete_fee(fid):
    execute("DELETE FROM price WHERE id=%s", (fid,))
    return jsonify({"success": True})
