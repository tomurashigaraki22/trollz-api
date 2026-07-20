from flask import Blueprint, jsonify, request
from lib.db import query, query_one, execute

users_bp = Blueprint("users", __name__)

def column_exists(table, column):
    result = query_one(
        "SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s LIMIT 1",
        (table, column),
    )
    return bool(result)

@users_bp.route("", methods=["GET"])
def get_users():
    role = request.args.get("role", "").strip()
    if role:
        return jsonify(query(
            "SELECT id, name, email, phone, role, store_name FROM users WHERE role=%s ORDER BY id DESC",
            (role,),
        ))
    return jsonify(query(
        "SELECT id, name, email, phone, role FROM users ORDER BY id DESC"
    ))

@users_bp.route("", methods=["POST"])
def create_user():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    password = data.get("password") or ""
    store_name = (data.get("store_name") or "").strip()
    role = (data.get("role") or "Seller").strip() or "Seller"

    if not name or not email:
        return jsonify({"error": "Name and email are required"}), 400

    if query_one("SELECT id FROM users WHERE email=%s LIMIT 1", (email,)):
        return jsonify({"error": "Email already exists"}), 409

    columns = ["name", "email", "role"]
    values = [name, email, role]

    if column_exists("users", "phone") and phone:
        columns.append("phone")
        values.append(phone)

    if column_exists("users", "password"):
        columns.append("password")
        values.append(password)

    if column_exists("users", "store_name") and store_name:
        columns.append("store_name")
        values.append(store_name)

    user_id = execute(
        f"INSERT INTO users ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(values))})",
        tuple(values),
    )

    return jsonify({
        "success": True,
        "user": {
            "id": user_id,
            "name": name,
            "email": email,
            "phone": phone,
            "role": role,
            "store_name": store_name,
        },
    }), 201

@users_bp.route("/<int:uid>", methods=["DELETE"])
def delete_user(uid):
    execute("DELETE FROM users WHERE id=%s", (uid,))
    return jsonify({"success": True})

@users_bp.route("/<int:uid>/role", methods=["PATCH"])
def update_user_role(uid):
    data = request.get_json(silent=True) or {}
    role = data.get("role", "").strip()
    if not role:
        return jsonify({"error": "Role is required"}), 400

    execute("UPDATE users SET role=%s WHERE id=%s", (role, uid))
    return jsonify({"success": True, "role": role})
