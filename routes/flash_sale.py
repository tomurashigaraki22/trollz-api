from flask import Blueprint, jsonify
from lib.db import query_one, execute

flash_sale_bp = Blueprint("flash_sale", __name__)

@flash_sale_bp.route("", methods=["GET"])
def get_status():
    row = query_one(
        "SELECT COUNT(*) as count FROM product WHERE is_flash_sale=1 AND flash_sale_end > NOW()"
    )
    return jsonify({"active": (row["count"] > 0) if row else False})

@flash_sale_bp.route("", methods=["POST"])
def generate():
    execute(
        "UPDATE product SET is_flash_sale=1, flash_sale_end=DATE_ADD(NOW(), INTERVAL 24 HOUR) "
        "WHERE qty > 0 ORDER BY RAND() LIMIT 10"
    )
    return jsonify({"success": True})

@flash_sale_bp.route("", methods=["DELETE"])
def end_sale():
    execute("UPDATE product SET is_flash_sale=0, flash_sale_end=NULL")
    return jsonify({"success": True})
