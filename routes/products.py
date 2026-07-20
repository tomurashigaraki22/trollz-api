import json
from flask import Blueprint, request, jsonify
from lib.db import query, query_one, execute
from lib.cloudinary_helper import upload_image

products_bp = Blueprint("products", __name__)

@products_bp.route("", methods=["GET"])
def get_products():
    parent_id = request.args.get("parent_id")
    subcat_id = request.args.get("subcat_id")

    sql = """
        SELECT p.*, c.category as parent_name, sc.category as subcat_name
        FROM product p
        LEFT JOIN category c ON p.parent_category_id = c.id
        LEFT JOIN category sc ON p.subcategory_id = sc.id
        WHERE 1=1
    """
    params = []
    if parent_id:
        sql += " AND p.parent_category_id = %s"
        params.append(parent_id)
    if subcat_id:
        sql += " AND p.subcategory_id = %s"
        params.append(subcat_id)
    sql += " ORDER BY p.id DESC"

    return jsonify(query(sql, params))

@products_bp.route("/<int:pid>", methods=["GET"])
def get_product(pid):
    p = query_one("SELECT * FROM product WHERE id = %s", (pid,))
    if not p:
        return jsonify({"error": "Not found"}), 404
    return jsonify(p)

@products_bp.route("", methods=["POST"])
def create_product():
    item = request.form.get("item")
    qty = request.form.get("qty")
    parent_category_id = request.form.get("parent_category_id")
    subcategory_id = request.form.get("subcategory_id")
    price = request.form.get("price")
    discount = request.form.get("discount", 0)
    description = request.form.get("description")
    shipped = request.form.get("shipped_from_abroad", "no")
    size_type = request.form.get("size_type")
    size_options = request.form.get("size_options", "[]")

    images = request.files.getlist("images")
    urls = []
    for f in images:
        if f.filename:
            urls.append(upload_image(f.stream, "trollz/products"))

    execute(
        """INSERT INTO product (item, qty, parent_category_id, subcategory_id, price, discount,
           description, shipped_from_abroad, size_type, size_options, img, new)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""",
        (item, qty, parent_category_id, subcategory_id, price, discount,
         description, shipped, size_type, size_options, json.dumps(urls))
    )
    return jsonify({"success": True})

@products_bp.route("/<int:pid>", methods=["PUT"])
def update_product(pid):
    item = request.form.get("item")
    qty = request.form.get("qty")
    parent_category_id = request.form.get("parent_category_id")
    subcategory_id = request.form.get("subcategory_id")
    price = request.form.get("price")
    discount = request.form.get("discount", 0)
    description = request.form.get("description")
    shipped = request.form.get("shipped_from_abroad", "no")
    size_type = request.form.get("size_type")
    size_options = request.form.get("size_options", "[]")
    existing_images = request.form.get("existing_images", "[]")

    images = request.files.getlist("images")
    img_json = existing_images
    if images and images[0].filename:
        urls = [upload_image(f.stream, "trollz/products") for f in images if f.filename]
        img_json = json.dumps(urls)

    execute(
        """UPDATE product SET item=%s, qty=%s, parent_category_id=%s, subcategory_id=%s,
           price=%s, discount=%s, description=%s, shipped_from_abroad=%s,
           size_type=%s, size_options=%s, img=%s WHERE id=%s""",
        (item, qty, parent_category_id, subcategory_id, price, discount,
         description, shipped, size_type, size_options, img_json, pid)
    )
    return jsonify({"success": True})

@products_bp.route("/<int:pid>", methods=["PATCH"])
def patch_product(pid):
    data = request.get_json()
    execute("UPDATE product SET qty=%s WHERE id=%s", (data["qty"], pid))
    return jsonify({"success": True})

@products_bp.route("/<int:pid>", methods=["DELETE"])
def delete_product(pid):
    execute("DELETE FROM product WHERE id=%s", (pid,))
    return jsonify({"success": True})
