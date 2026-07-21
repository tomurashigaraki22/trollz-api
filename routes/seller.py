import os
import json
import uuid
from datetime import datetime, timedelta
import bcrypt
from flask import Blueprint, request, jsonify
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from lib.db import query, query_one, execute
from lib.cloudinary_helper import upload_image

seller_bp = Blueprint("seller", __name__)

SELLER_ROLES = ("Seller", "Admin", "Manager", "Support", "Viewer")
DEFAULT_SELLER_EMAIL = "devtomiwa9@gmail.com"
DEFAULT_SELLER_NAME = "Tomiwa Store"
DEFAULT_SELLER_PASSWORD = "Pityboy@22"
DEFAULT_SELLER_STORE = "Tomiwa Store"

_TOKEN_SECRET = os.getenv("SELLER_TOKEN_SECRET") or os.getenv("SECRET_KEY") or "trollz-secret"
_TOKEN_MAX_AGE = 60 * 60 * 24 * 7
_serializer = URLSafeTimedSerializer(_TOKEN_SECRET)
_SCHEMA_CACHE = {}


def column_exists(table, column):
    key = (table, column)
    if key in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[key]

    try:
        result = query_one(
            "SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s LIMIT 1",
            (table, column),
        )
        exists = bool(result)
    except Exception:
        exists = False

    _SCHEMA_CACHE[key] = exists
    return exists


def ensure_seller_tables():
    try:
        execute(
            """
            CREATE TABLE IF NOT EXISTS seller_products (
                id INT AUTO_INCREMENT PRIMARY KEY,
                seller_id INT,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                price DECIMAL(12,2) NOT NULL DEFAULT 0.00,
                stock INT NOT NULL DEFAULT 0,
                category VARCHAR(128),
                status VARCHAR(50) DEFAULT 'active',
                image_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        )

        execute(
            """
            CREATE TABLE IF NOT EXISTS seller_orders (
                id INT AUTO_INCREMENT PRIMARY KEY,
                seller_id INT,
                order_number VARCHAR(100),
                buyer_name VARCHAR(255),
                buyer_email VARCHAR(255),
                total_amount DECIMAL(12,2) DEFAULT 0.00,
                order_status VARCHAR(50) DEFAULT 'pending',
                payment_status VARCHAR(50) DEFAULT 'pending',
                city VARCHAR(128),
                delivery_city VARCHAR(128),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        )

        execute(
            """
            CREATE TABLE IF NOT EXISTS seller_team (
                id INT AUTO_INCREMENT PRIMARY KEY,
                seller_id INT,
                name VARCHAR(255),
                email VARCHAR(255),
                role VARCHAR(50) DEFAULT 'viewer',
                password VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        )

        if not column_exists("seller_products", "storefront_product_id"):
            execute("ALTER TABLE seller_products ADD COLUMN storefront_product_id INT NULL")
    except Exception as exc:
        print("Unable to create seller tables:", exc)


def get_seller_store_name(seller_id):
    seller = query_one("SELECT name, email FROM users WHERE id=%s LIMIT 1", (seller_id,))
    return (seller or {}).get("name") or (seller or {}).get("email") or DEFAULT_SELLER_STORE


def product_images_json(image_url):
    return json.dumps([image_url]) if image_url else json.dumps([])


def resolve_storefront_category(category_name):
    category = (category_name or "").strip()
    if category:
        existing = query_one(
            "SELECT id, category, parent_id FROM category WHERE LOWER(category)=LOWER(%s) LIMIT 1",
            (category,),
        )
        if existing:
            if existing.get("parent_id"):
                parent = query_one("SELECT id, category FROM category WHERE id=%s LIMIT 1", (existing["parent_id"],))
                return {
                    "category": (parent or existing).get("category"),
                    "category_id": (parent or existing).get("id"),
                    "subcategory": existing.get("category"),
                    "subcategory_id": existing.get("id"),
                }
            return {
                "category": existing.get("category"),
                "category_id": existing.get("id"),
                "subcategory": "",
                "subcategory_id": None,
            }

    fallback = query_one("SELECT id, category FROM category WHERE parent_id IS NULL ORDER BY id LIMIT 1")
    if fallback:
        return {
            "category": fallback.get("category"),
            "category_id": fallback.get("id"),
            "subcategory": "",
            "subcategory_id": None,
        }
    return {"category": category or "Marketplace", "category_id": 1, "subcategory": "", "subcategory_id": None}


def sync_seller_product_to_storefront(seller_product):
    if not seller_product or seller_product.get("status") == "draft":
        return None

    seller_id = seller_product.get("seller_id")
    supplier = get_seller_store_name(seller_id)
    name = seller_product.get("name") or "Seller product"
    price = seller_product.get("price") or 0
    stock = seller_product.get("stock") or 0
    category_info = resolve_storefront_category(seller_product.get("category"))
    description = seller_product.get("description") or ""
    image_json = product_images_json(seller_product.get("image_url"))
    existing_product_id = seller_product.get("storefront_product_id")

    if existing_product_id:
        execute(
            """
            UPDATE product
            SET item=%s, category=%s, subcategory=%s, parent_category_id=%s, subcategory_id=%s,
                category_id=%s, price=%s, old_price=%s, discount=0,
                description=%s, supplier=%s, img=%s, qty=%s, stock=%s, new=%s
            WHERE id=%s
            """,
            (
                name,
                category_info["category"],
                category_info["subcategory"],
                category_info["category_id"],
                category_info["subcategory_id"],
                category_info["category_id"],
                price,
                price,
                description,
                supplier,
                image_json,
                stock,
                stock,
                1,
                existing_product_id,
            ),
        )
        return existing_product_id

    storefront_product_id = execute(
        """
        INSERT INTO product
            (item, category, subcategory, parent_category_id, subcategory_id, category_id,
             price, old_price, discount, description, supplier, new, img, qty, stock, date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, NOW())
        """,
        (
            name,
            category_info["category"],
            category_info["subcategory"],
            category_info["category_id"],
            category_info["subcategory_id"],
            category_info["category_id"],
            price,
            price,
            description,
            supplier,
            1,
            image_json,
            stock,
            stock,
        ),
    )
    execute(
        "UPDATE seller_products SET storefront_product_id=%s WHERE id=%s AND seller_id=%s",
        (storefront_product_id, seller_product.get("id"), seller_id),
    )
    return storefront_product_id


def remove_seller_product_from_storefront(seller_product):
    storefront_product_id = (seller_product or {}).get("storefront_product_id")
    if storefront_product_id:
        execute("DELETE FROM product WHERE id=%s", (storefront_product_id,))


def load_seller_from_token():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    try:
        data = _serializer.loads(token, max_age=_TOKEN_MAX_AGE)
        return data if isinstance(data, dict) else None
    except (BadSignature, SignatureExpired):
        return None


def create_token(user):
    payload = {
        "seller_id": user.get("seller_id") or user.get("id"),
        "email": user.get("email"),
        "name": user.get("name"),
        "role": user.get("role"),
    }
    return _serializer.dumps(payload)


def is_bcrypt_hash(value):
    return isinstance(value, str) and value.startswith(("$2a$", "$2b$", "$2y$"))


def verify_password(user, password, table_name=None):
    stored_password = user.get("password") if user else None
    if not stored_password:
        return False

    if is_bcrypt_hash(stored_password):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_password.encode("utf-8"))
        except ValueError:
            return False

    matches = stored_password == password
    if matches and table_name == "users":
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        execute("UPDATE users SET password=%s WHERE id=%s", (hashed, user.get("id")))
    return matches


def get_seller_id():
    token_data = load_seller_from_token()
    if token_data and token_data.get("seller_id"):
        return token_data["seller_id"]
    return None


def percent(numerator, denominator):
    numerator = float(numerator or 0)
    denominator = float(denominator or 0)
    if denominator <= 0:
        return 0
    return round((numerator / denominator) * 100, 1)


def get_seller_rating_summary(seller_id):
    try:
        if not column_exists("product_reviews", "rating"):
            return {"average_rating": 0, "rating_count": 0}

        if column_exists("product", "seller_id"):
            rating = query_one(
                """
                SELECT COALESCE(AVG(pr.rating), 0) AS average_rating, COUNT(*) AS rating_count
                FROM product_reviews pr
                JOIN product p ON p.id = pr.product_id
                WHERE p.seller_id = %s
                """,
                (seller_id,),
            )
            return {
                "average_rating": round(float(rating["average_rating"] or 0), 1) if rating else 0,
                "rating_count": int(rating["rating_count"] or 0) if rating else 0,
            }

        if column_exists("product_reviews", "seller_id"):
            rating = query_one(
                """
                SELECT COALESCE(AVG(rating), 0) AS average_rating, COUNT(*) AS rating_count
                FROM product_reviews
                WHERE seller_id = %s
                """,
                (seller_id,),
            )
            return {
                "average_rating": round(float(rating["average_rating"] or 0), 1) if rating else 0,
                "rating_count": int(rating["rating_count"] or 0) if rating else 0,
            }
    except Exception as exc:
        print("Unable to calculate seller ratings:", exc)

    return {"average_rating": 0, "rating_count": 0}


def create_default_seller():
    try:
        if not column_exists("users", "email") or not column_exists("users", "name"):
            return

        existing = query_one("SELECT id FROM users WHERE email=%s LIMIT 1", (DEFAULT_SELLER_EMAIL,))
        if existing:
            return

        columns = ["name", "email", "role"]
        values = [DEFAULT_SELLER_NAME, DEFAULT_SELLER_EMAIL, "Seller"]

        if column_exists("users", "password"):
            columns.append("password")
            values.append(DEFAULT_SELLER_PASSWORD)

        if column_exists("users", "store_name"):
            columns.append("store_name")
            values.append(DEFAULT_SELLER_STORE)

        execute(
            f"INSERT INTO users ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
            tuple(values),
        )
    except Exception as exc:
        print("Unable to create default seller account:", exc)


def initialize_seller_module():
    ensure_seller_tables()
    create_default_seller()


@seller_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = query_one(
        "SELECT id, email, name, password, role, status FROM users WHERE LOWER(email)=LOWER(%s) LIMIT 1",
        (email,),
    )
    user_table = "users" if user else None

    if not user:
        user = query_one(
            "SELECT id, seller_id, email, name, password, role FROM seller_team WHERE LOWER(email)=LOWER(%s) LIMIT 1",
            (email,),
        )
        user_table = "seller_team" if user else None

    password_matches = verify_password(user, password, user_table) if user else False
    if not user or not password_matches:
        return jsonify({"error": "Invalid credentials"}), 401

    if user.get("role") not in SELLER_ROLES:
        return jsonify({"error": "Not authorized"}), 403

    if user_table == "users" and str(user.get("status", 1)) in ("0", "False", "false"):
        return jsonify({"error": "Seller account is inactive"}), 403

    token = create_token(user)
    return jsonify({
        "success": True,
        "data": {
            "token": token,
            "seller": {
                "id": user.get("id"),
                "name": user.get("name"),
                "email": user.get("email"),
                "store_name": user.get("name") or DEFAULT_SELLER_STORE,
            },
        },
    })


@seller_bp.route("/dashboard", methods=["GET"])
def dashboard():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"success": True, "data": {"summary": {}, "recent_orders": [], "orders_chart": []}})

    total_products = query_one("SELECT COUNT(*) as count FROM seller_products WHERE seller_id=%s", (seller_id,))
    low_stock = query_one("SELECT COUNT(*) as count FROM seller_products WHERE seller_id=%s AND stock <= 5", (seller_id,))
    total_orders = query_one("SELECT COUNT(*) as count FROM seller_orders WHERE seller_id=%s", (seller_id,))
    total_sales = query_one("SELECT COALESCE(SUM(total_amount), 0) as total FROM seller_orders WHERE seller_id=%s AND payment_status='paid'", (seller_id,))
    paid_orders = query_one("SELECT COUNT(*) as count FROM seller_orders WHERE seller_id=%s AND payment_status='paid'", (seller_id,))
    cancelled_orders = query_one("SELECT COUNT(*) as count FROM seller_orders WHERE seller_id=%s AND order_status='cancelled'", (seller_id,))
    delivered_orders = query_one("SELECT COUNT(*) as count FROM seller_orders WHERE seller_id=%s AND order_status IN ('delivered', 'completed')", (seller_id,))
    monthly_sales = query_one(
        "SELECT COALESCE(SUM(total_amount), 0) as total FROM seller_orders WHERE seller_id=%s AND payment_status='paid' AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)",
        (seller_id,),
    )
    monthly_orders = query_one(
        "SELECT COUNT(*) as count FROM seller_orders WHERE seller_id=%s AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)",
        (seller_id,),
    )

    product_views = {"total": 0}
    if column_exists("seller_products", "views"):
        product_views = query_one("SELECT COALESCE(SUM(views), 0) as total FROM seller_products WHERE seller_id=%s", (seller_id,)) or {"total": 0}

    total_orders_count = int(total_orders["count"] or 0) if total_orders else 0
    paid_orders_count = int(paid_orders["count"] or 0) if paid_orders else 0
    cancelled_orders_count = int(cancelled_orders["count"] or 0) if cancelled_orders else 0
    delivered_orders_count = int(delivered_orders["count"] or 0) if delivered_orders else 0
    views_count = int(product_views["total"] or 0) if product_views else 0
    conversion_denominator = views_count if views_count > 0 else total_orders_count
    ratings = get_seller_rating_summary(seller_id)
    monthly_sales_total = float(monthly_sales["total"] or 0) if monthly_sales else 0
    monthly_orders_count = int(monthly_orders["count"] or 0) if monthly_orders else 0
    cancellation_rate = percent(cancelled_orders_count, total_orders_count)
    conversion_rate = percent(paid_orders_count, conversion_denominator)
    fulfillment_rate = percent(delivered_orders_count, total_orders_count)
    is_top_seller = (
        monthly_sales_total >= 100000
        and monthly_orders_count >= 10
        and cancellation_rate <= 5
        and (ratings["average_rating"] >= 4.5 or ratings["rating_count"] == 0)
    )

    recent_orders = query(
        "SELECT id, order_number, buyer_name, total_amount, order_status, payment_status, created_at FROM seller_orders WHERE seller_id=%s ORDER BY created_at DESC LIMIT 5",
        (seller_id,),
    )

    orders_chart = query(
        "SELECT DATE(created_at) as day, COALESCE(SUM(total_amount), 0) as total FROM seller_orders WHERE seller_id=%s AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY) GROUP BY DATE(created_at) ORDER BY day ASC",
        (seller_id,),
    )

    for row in orders_chart:
        if row.get("day"):
            row["day"] = str(row["day"])

    return jsonify({
        "success": True,
        "data": {
            "summary": {
                "total_products": total_products["count"] if total_products else 0,
                "low_stock_products": low_stock["count"] if low_stock else 0,
                "total_orders": total_orders["count"] if total_orders else 0,
                "total_sales": float(total_sales["total"]) if total_sales else 0,
                "paid_orders": paid_orders_count,
                "monthly_sales": monthly_sales_total,
                "monthly_orders": monthly_orders_count,
                "conversion_rate": conversion_rate,
                "cancellation_rate": cancellation_rate,
                "fulfillment_rate": fulfillment_rate,
                "average_rating": ratings["average_rating"],
                "rating_count": ratings["rating_count"],
                "top_seller_badge": is_top_seller,
                "badge_label": "Top Seller" if is_top_seller else "Growing Seller",
            },
            "recent_orders": recent_orders,
            "orders_chart": orders_chart,
        },
    })


@seller_bp.route("/products", methods=["GET"])
def get_products():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"success": True, "data": []})

    params = []
    sql = "SELECT * FROM seller_products WHERE seller_id = %s"
    params.append(seller_id)

    category = request.args.get("category")
    status = request.args.get("status")
    if category:
        sql += " AND category = %s"
        params.append(category)
    if status:
        sql += " AND status = %s"
        params.append(status)

    sql += " ORDER BY id DESC"
    products = query(sql, params)
    for product in products:
        if product.get("status") != "draft":
            sync_seller_product_to_storefront(product)
    return jsonify({"success": True, "data": query(sql, params)})


@seller_bp.route("/products", methods=["POST"])
def create_product():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    name = data.get("name") or data.get("item")
    price = data.get("price") or 0
    stock = data.get("stock") or data.get("qty") or 0
    category = data.get("category")
    description = data.get("description")
    status = data.get("status") or "active"
    image_url = data.get("image_url") or data.get("img")

    product_id = execute(
        "INSERT INTO seller_products (seller_id, name, description, price, stock, category, status, image_url) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (seller_id, name, description, price, stock, category, status, image_url),
    )
    product = query_one("SELECT * FROM seller_products WHERE id=%s AND seller_id=%s", (product_id, seller_id))
    sync_seller_product_to_storefront(product)
    product = query_one("SELECT * FROM seller_products WHERE id=%s AND seller_id=%s", (product_id, seller_id))
    return jsonify({"success": True, "data": product})


@seller_bp.route("/products/<int:pid>", methods=["PUT"])
def update_product(pid):
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    name = data.get("name") or data.get("item")
    price = data.get("price") or 0
    stock = data.get("stock") or data.get("qty") or 0
    category = data.get("category")
    description = data.get("description")
    status = data.get("status") or "active"
    image_url = data.get("image_url") or data.get("img")

    execute(
        "UPDATE seller_products SET name=%s, description=%s, price=%s, stock=%s, category=%s, status=%s, image_url=%s WHERE id=%s AND seller_id=%s",
        (name, description, price, stock, category, status, image_url, pid, seller_id),
    )
    product = query_one("SELECT * FROM seller_products WHERE id=%s AND seller_id=%s", (pid, seller_id))
    if product and status == "draft":
        remove_seller_product_from_storefront(product)
        execute("UPDATE seller_products SET storefront_product_id=NULL WHERE id=%s AND seller_id=%s", (pid, seller_id))
    else:
        sync_seller_product_to_storefront(product)
    return jsonify({"success": True})


@seller_bp.route("/products/<int:pid>", methods=["DELETE"])
def delete_product(pid):
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401

    product = query_one("SELECT * FROM seller_products WHERE id=%s AND seller_id=%s", (pid, seller_id))
    remove_seller_product_from_storefront(product)
    execute("DELETE FROM seller_products WHERE id=%s AND seller_id=%s", (pid, seller_id))
    return jsonify({"success": True})


@seller_bp.route("/products/upload", methods=["POST"])
def upload_product_image():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401

    file = request.files.get("image")
    if not file:
        return jsonify({"error": "No image provided"}), 400

    url = upload_image(file.stream, "trollz/seller/products")
    return jsonify({"url": url})


@seller_bp.route("/orders", methods=["GET"])
def get_orders():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify([])

    sql = "SELECT * FROM seller_orders WHERE seller_id=%s"
    params = [seller_id]
    status = request.args.get("status")
    if status and status != "all":
        sql += " AND payment_status = %s"
        params.append(status)

    sql += " ORDER BY created_at DESC"
    return jsonify(query(sql, params))


@seller_bp.route("/orders/<int:oid>", methods=["GET"])
def get_order(oid):
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401

    order = query_one("SELECT * FROM seller_orders WHERE id=%s AND seller_id=%s", (oid, seller_id))
    if not order:
        return jsonify({"error": "Not found"}), 404
    return jsonify(order)


@seller_bp.route("/analytics", methods=["GET"])
def analytics():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"success": True, "data": {}})

    range_value = request.args.get("range", "7d")
    interval = "7 DAY"
    if range_value == "30d":
        interval = "30 DAY"
    elif range_value == "90d":
        interval = "90 DAY"

    summary = query_one(
        "SELECT COUNT(*) as total_orders, COALESCE(SUM(total_amount), 0) as total_revenue FROM seller_orders WHERE seller_id=%s AND created_at >= DATE_SUB(NOW(), INTERVAL %s)",
        (seller_id, interval),
    )
    orders_chart = query(
        "SELECT DATE(created_at) as day, COALESCE(COUNT(*), 0) as count, COALESCE(SUM(total_amount), 0) as revenue FROM seller_orders WHERE seller_id=%s AND created_at >= DATE_SUB(NOW(), INTERVAL %s) GROUP BY DATE(created_at) ORDER BY day ASC",
        (seller_id, interval),
    )
    revenue_chart = query(
        "SELECT DATE(created_at) as day, COALESCE(SUM(total_amount), 0) as revenue FROM seller_orders WHERE seller_id=%s AND created_at >= DATE_SUB(NOW(), INTERVAL %s) GROUP BY DATE(created_at) ORDER BY day ASC",
        (seller_id, interval),
    )
    top_locations = query(
        "SELECT COALESCE(delivery_city, city) as label, COALESCE(SUM(total_amount), 0) as value FROM seller_orders WHERE seller_id=%s AND created_at >= DATE_SUB(NOW(), INTERVAL %s) GROUP BY COALESCE(delivery_city, city) ORDER BY value DESC LIMIT 5",
        (seller_id, interval),
    )
    top_products = query(
        "SELECT buyer_name as label, COALESCE(SUM(total_amount), 0) as value FROM seller_orders WHERE seller_id=%s AND created_at >= DATE_SUB(NOW(), INTERVAL %s) GROUP BY buyer_name ORDER BY value DESC LIMIT 5",
        (seller_id, interval),
    )

    for row in orders_chart + revenue_chart:
        if row.get("day"):
            row["day"] = str(row["day"])

    return jsonify({
        "success": True,
        "data": {
            "summary": {
                "total_orders": summary["total_orders"] if summary else 0,
                "total_revenue": float(summary["total_revenue"]) if summary else 0,
            },
            "orders_chart": orders_chart,
            "revenue_chart": revenue_chart,
            "top_locations": top_locations,
            "top_products": top_products,
        },
    })


@seller_bp.route("/team", methods=["GET"])
def get_team():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify([])

    members = query("SELECT id, name, email, role FROM seller_team WHERE seller_id=%s ORDER BY id DESC", (seller_id,))
    return jsonify(members)


@seller_bp.route("/team/invite", methods=["POST"])
def invite_team_member():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    email = data.get("email")
    name = data.get("name")
    role = data.get("role") or "viewer"
    password = data.get("password") or str(uuid.uuid4())

    if not email:
        return jsonify({"error": "Email is required"}), 400

    execute(
        "INSERT INTO seller_team (seller_id, name, email, role, password) VALUES (%s, %s, %s, %s, %s)",
        (seller_id, name, email, role, password),
    )
    return jsonify({"success": True})


@seller_bp.route("/team/<int:uid>", methods=["DELETE"])
def remove_team_member(uid):
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401

    execute("DELETE FROM seller_team WHERE id=%s AND seller_id=%s", (uid, seller_id))
    return jsonify({"success": True})


@seller_bp.route("/team/<int:uid>/role", methods=["PATCH"])
def update_team_member_role(uid):
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    role = data.get("role")
    if not role:
        return jsonify({"error": "Role is required"}), 400

    execute("UPDATE seller_team SET role=%s WHERE id=%s AND seller_id=%s", (role, uid, seller_id))
    return jsonify({"success": True})
