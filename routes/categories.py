from flask import Blueprint, request, jsonify
from lib.db import query, query_one, execute
from lib.cloudinary_helper import upload_image

categories_bp = Blueprint("categories", __name__)

@categories_bp.route("", methods=["GET"])
def get_categories():
    return jsonify(query("SELECT * FROM category ORDER BY parent_id ASC, id ASC"))

@categories_bp.route("/subcategories", methods=["GET"])
def get_subcategories():
    parent_id = request.args.get("parent_id")
    if not parent_id:
        return jsonify([])
    return jsonify(query(
        "SELECT id, category FROM category WHERE parent_id = %s ORDER BY category ASC",
        (parent_id,)
    ))

@categories_bp.route("", methods=["POST"])
def create_category():
    name = request.form.get("category")
    parent_id = request.form.get("parent_id") or None
    bg_color = request.form.get("bg_color")
    icon_file = request.files.get("icon")

    icon_url = None
    if icon_file and icon_file.filename:
        icon_url = upload_image(icon_file.stream, "trollz/icons")

    execute(
        "INSERT INTO category (category, parent_id, bg_color, icon) VALUES (%s,%s,%s,%s)",
        (name, parent_id, bg_color, icon_url)
    )
    return jsonify({"success": True})

@categories_bp.route("/<int:cid>", methods=["PUT"])
def update_category(cid):
    name = request.form.get("category")
    parent_id = request.form.get("parent_id") or None
    bg_color = request.form.get("bg_color")
    icon_file = request.files.get("icon")
    existing_icon = request.form.get("existing_icon")

    icon_url = existing_icon
    if icon_file and icon_file.filename:
        icon_url = upload_image(icon_file.stream, "trollz/icons")

    execute(
        "UPDATE category SET category=%s, parent_id=%s, bg_color=%s, icon=%s WHERE id=%s",
        (name, parent_id, bg_color, icon_url, cid)
    )
    return jsonify({"success": True})

@categories_bp.route("/<int:cid>", methods=["DELETE"])
def delete_category(cid):
    execute("DELETE FROM category WHERE parent_id=%s", (cid,))
    execute("DELETE FROM category WHERE id=%s", (cid,))
    return jsonify({"success": True})
