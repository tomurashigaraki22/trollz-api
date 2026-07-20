from flask import Blueprint, request, jsonify
from lib.db import query_one

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/verify", methods=["POST"])
def verify():
    data = request.get_json()
    email = data.get("email", "")
    password = data.get("password", "")

    user = query_one(
        "SELECT id, email, name, password, role FROM users WHERE email = %s LIMIT 1",
        (email,)
    )

    if not user:
        return jsonify({"error": "Invalid credentials"}), 401
    if user["password"] != password:
        return jsonify({"error": "Invalid credentials"}), 401
    if user["role"] != "Admin":
        return jsonify({"error": "Not authorized"}), 403

    return jsonify({
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
    })
