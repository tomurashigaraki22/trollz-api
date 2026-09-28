import os
import json
import uuid
from datetime import datetime, timedelta
import bcrypt
import requests
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
                subcategory VARCHAR(128),
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

        execute(
            """
            CREATE TABLE IF NOT EXISTS seller_delivery_settings (
                seller_id INT PRIMARY KEY,
                pickup_zone_id INT NULL,
                pickup_address TEXT,
                handling_time_days INT NOT NULL DEFAULT 1,
                same_day_pickup TINYINT(1) NOT NULL DEFAULT 0,
                dropoff_supported TINYINT(1) NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        )

        execute(
            """
            CREATE TABLE IF NOT EXISTS delivery_zones (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                state VARCHAR(120),
                cities TEXT,
                base_fee DECIMAL(12,2) NOT NULL DEFAULT 0,
                express_fee DECIMAL(12,2) NOT NULL DEFAULT 0,
                extra_seller_fee DECIMAL(12,2) NOT NULL DEFAULT 0,
                inter_zone_fee DECIMAL(12,2) NOT NULL DEFAULT 0,
                batch_discount DECIMAL(12,2) NOT NULL DEFAULT 0,
                free_delivery_threshold DECIMAL(12,2) NOT NULL DEFAULT 0,
                standard_min_days INT NOT NULL DEFAULT 1,
                standard_max_days INT NOT NULL DEFAULT 3,
                express_min_days INT NOT NULL DEFAULT 0,
                express_max_days INT NOT NULL DEFAULT 1,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        )

        execute(
            """
            CREATE TABLE IF NOT EXISTS seller_banner_ad_plans (
                code VARCHAR(32) PRIMARY KEY,
                name VARCHAR(80) NOT NULL,
                duration_days INT NOT NULL,
                price DECIMAL(12,2) NOT NULL DEFAULT 0.00,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        )
        execute(
            """
            INSERT IGNORE INTO seller_banner_ad_plans (code, name, duration_days, price, is_active)
            VALUES
                ('monthly', 'Monthly', 30, 0.00, 1),
                ('quarterly', 'Quarterly (3 months)', 90, 0.00, 1),
                ('yearly', 'Yearly', 365, 0.00, 1)
            """,
        )
        execute(
            """
            CREATE TABLE IF NOT EXISTS seller_banner_ads (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                seller_id INT NOT NULL,
                plan_code VARCHAR(32) NOT NULL,
                amount DECIMAL(12,2) NOT NULL DEFAULT 0.00,
                image_url TEXT NOT NULL,
                target_url TEXT NULL,
                tx_ref VARCHAR(160) NOT NULL UNIQUE,
                transaction_id VARCHAR(100) NULL,
                payment_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                starts_at DATETIME NULL,
                expires_at DATETIME NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_seller_banner_ads_seller (seller_id, status),
                KEY idx_seller_banner_ads_live (status, payment_status, starts_at, expires_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        )

        if not column_exists("seller_products", "storefront_product_id"):
            execute("ALTER TABLE seller_products ADD COLUMN storefront_product_id INT NULL")
        if not column_exists("seller_products", "subcategory"):
            execute("ALTER TABLE seller_products ADD COLUMN subcategory VARCHAR(128) NULL")
        for column, definition in (
            ("size_type", "VARCHAR(50) NULL"),
            ("size_options", "TEXT NULL"),
            ("color_options", "TEXT NULL"),
            ("attributes", "TEXT NULL"),
        ):
            if not column_exists("seller_products", column):
                execute(f"ALTER TABLE seller_products ADD COLUMN {column} {definition}")
        if not column_exists("product", "attributes"):
            execute("ALTER TABLE product ADD COLUMN attributes TEXT NULL")
    except Exception as exc:
        print("Unable to create seller tables:", exc)


def get_seller_store_name(seller_id):
    seller = query_one("SELECT name, email FROM users WHERE id=%s LIMIT 1", (seller_id,))
    return (seller or {}).get("name") or (seller or {}).get("email") or DEFAULT_SELLER_STORE


def product_images_json(image_url):
    if not image_url:
        return json.dumps([])
    if isinstance(image_url, list):
        return json.dumps([url for url in image_url if url])
    if isinstance(image_url, str):
        value = image_url.strip()
        if not value:
            return json.dumps([])
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return json.dumps([url for url in parsed if url])
        except Exception:
            pass
        return json.dumps([value])
    return json.dumps([])


def json_list(value):
    if isinstance(value, list):
        return [item for item in value if item]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return [item for item in parsed if item] if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def json_object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def resolve_storefront_category(category_name, subcategory_name=None):
    category = (category_name or "").strip()
    subcategory = (subcategory_name or "").strip()
    if subcategory:
        existing = query_one(
            "SELECT id, category, parent_id FROM category WHERE LOWER(category)=LOWER(%s) LIMIT 1",
            (subcategory,),
        )
        if existing and existing.get("parent_id"):
            parent = query_one("SELECT id, category FROM category WHERE id=%s LIMIT 1", (existing["parent_id"],))
            if not category or (parent and parent.get("category", "").lower() == category.lower()):
                return {
                    "category": (parent or existing).get("category"),
                    "category_id": (parent or existing).get("id"),
                    "subcategory": existing.get("category"),
                    "subcategory_id": existing.get("id"),
                }

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
    category_info = resolve_storefront_category(seller_product.get("category"), seller_product.get("subcategory"))
    description = seller_product.get("description") or ""
    image_json = product_images_json(seller_product.get("image_url"))
    size_type = seller_product.get("size_type") or "none"
    size_options = product_images_json(seller_product.get("size_options"))
    color_options = product_images_json(seller_product.get("color_options"))
    raw_attributes = seller_product.get("attributes") or {}
    attributes = raw_attributes if isinstance(raw_attributes, str) else json.dumps(raw_attributes)
    existing_product_id = seller_product.get("storefront_product_id")

    if existing_product_id:
        execute(
            """
            UPDATE product
            SET item=%s, category=%s, subcategory=%s, parent_category_id=%s, subcategory_id=%s,
                category_id=%s, price=%s, old_price=%s, discount=0,
                description=%s, supplier=%s, img=%s, qty=%s, stock=%s, new=%s,
                size_type=%s, size_options=%s, color_options=%s, attributes=%s
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
                size_type,
                size_options,
                color_options,
                attributes,
                existing_product_id,
            ),
        )
        return existing_product_id

    storefront_product_id = execute(
        """
        INSERT INTO product
            (item, category, subcategory, parent_category_id, subcategory_id, category_id,
             price, old_price, discount, description, supplier, new, img, qty, stock,
             size_type, size_options, color_options, attributes, date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, NOW())
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
            size_type,
            size_options,
            color_options,
            attributes,
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
        "onboarding_required": str(user.get("status", 1)) in ("0", "False", "false"),
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
        seller = query_one(
            "SELECT id, status FROM users WHERE id=%s AND role='Seller' LIMIT 1",
            (token_data["seller_id"],),
        )
        if not seller or str(seller.get("status", 1)) in ("0", "False", "false"):
            return None
        return seller["id"]
    return None


def serialize_banner_ad(row):
    if not row:
        return row
    result = dict(row)
    for key in ("amount",):
        if result.get(key) is not None:
            result[key] = float(result[key])
    for key in ("created_at", "updated_at", "starts_at", "expires_at"):
        if result.get(key):
            result[key] = str(result[key])
    return result


def valid_http_url(value):
    if not value:
        return None
    text = str(value).strip()
    if len(text) > 2048:
        return None
    if text.startswith(("https://", "http://")):
        return text
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

    token = create_token(user)
    onboarding_required = user_table == "users" and str(user.get("status", 1)) in ("0", "False", "false")
    return jsonify({
        "success": True,
        "data": {
            "token": token,
            "onboarding_required": onboarding_required,
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
    subcategory = data.get("subcategory")
    description = data.get("description")
    status = data.get("status") or "active"
    image_url = data.get("image_url") or data.get("image_urls") or data.get("img")
    size_options = json_list(data.get("size_options") or data.get("sizeOptions"))
    color_options = json_list(data.get("color_options") or data.get("colorOptions"))
    attributes = json_object(data.get("attributes"))
    size_type = data.get("size_type") or ("custom" if size_options else "none")

    product_id = execute(
        "INSERT INTO seller_products (seller_id, name, description, price, stock, category, subcategory, status, image_url, size_type, size_options, color_options, attributes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (seller_id, name, description, price, stock, category, subcategory, status, product_images_json(image_url), size_type, json.dumps(size_options), json.dumps(color_options), json.dumps(attributes)),
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
    subcategory = data.get("subcategory")
    description = data.get("description")
    status = data.get("status") or "active"
    image_url = data.get("image_url") or data.get("image_urls") or data.get("img")
    size_options = json_list(data.get("size_options") or data.get("sizeOptions"))
    color_options = json_list(data.get("color_options") or data.get("colorOptions"))
    attributes = json_object(data.get("attributes"))
    size_type = data.get("size_type") or ("custom" if size_options else "none")

    execute(
        "UPDATE seller_products SET name=%s, description=%s, price=%s, stock=%s, category=%s, subcategory=%s, status=%s, image_url=%s, size_type=%s, size_options=%s, color_options=%s, attributes=%s WHERE id=%s AND seller_id=%s",
        (name, description, price, stock, category, subcategory, status, product_images_json(image_url), size_type, json.dumps(size_options), json.dumps(color_options), json.dumps(attributes), pid, seller_id),
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


@seller_bp.route("/delivery-settings", methods=["GET"])
def get_delivery_settings():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401
    ensure_seller_tables()
    zones = query("SELECT id, name, state, cities FROM delivery_zones WHERE is_active=1 ORDER BY name")
    settings = query_one(
        "SELECT * FROM seller_delivery_settings WHERE seller_id=%s LIMIT 1",
        (seller_id,),
    ) or {
        "seller_id": seller_id,
        "pickup_zone_id": None,
        "pickup_address": "",
        "handling_time_days": 1,
        "same_day_pickup": 0,
        "dropoff_supported": 0,
    }
    return jsonify({"success": True, "data": {"settings": settings, "zones": zones}})


@seller_bp.route("/delivery-settings", methods=["PUT"])
def update_delivery_settings():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401
    ensure_seller_tables()
    data = request.get_json(force=True) or {}
    pickup_zone_id = data.get("pickup_zone_id") or None
    pickup_address = data.get("pickup_address") or ""
    handling_time_days = max(0, int(data.get("handling_time_days") or 1))
    same_day_pickup = 1 if data.get("same_day_pickup") else 0
    dropoff_supported = 1 if data.get("dropoff_supported") else 0
    execute(
        """
        INSERT INTO seller_delivery_settings
            (seller_id, pickup_zone_id, pickup_address, handling_time_days, same_day_pickup, dropoff_supported)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            pickup_zone_id=VALUES(pickup_zone_id),
            pickup_address=VALUES(pickup_address),
            handling_time_days=VALUES(handling_time_days),
            same_day_pickup=VALUES(same_day_pickup),
            dropoff_supported=VALUES(dropoff_supported)
        """,
        (seller_id, pickup_zone_id, pickup_address, handling_time_days, same_day_pickup, dropoff_supported),
    )
    settings = query_one("SELECT * FROM seller_delivery_settings WHERE seller_id=%s LIMIT 1", (seller_id,))
    return jsonify({"success": True, "data": {"settings": settings}})


@seller_bp.route("/banner-ads/plans", methods=["GET"])
def get_banner_ad_plans():
    ensure_seller_tables()
    plans = query(
        "SELECT code, name, duration_days, price FROM seller_banner_ad_plans WHERE is_active=1 ORDER BY duration_days"
    )
    for plan in plans:
        plan["price"] = float(plan.get("price") or 0)
        plan["duration_days"] = int(plan.get("duration_days") or 0)
    return jsonify({"success": True, "data": {"plans": plans}})


@seller_bp.route("/banner-ads", methods=["GET"])
def get_seller_banner_ads():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401
    ensure_seller_tables()
    ads = query(
        """
        SELECT a.*, p.name AS plan_name, p.duration_days
        FROM seller_banner_ads a
        JOIN seller_banner_ad_plans p ON p.code = a.plan_code
        WHERE a.seller_id=%s
        ORDER BY a.created_at DESC, a.id DESC
        """,
        (seller_id,),
    )
    return jsonify({"success": True, "data": {"ads": [serialize_banner_ad(ad) for ad in ads]}})


@seller_bp.route("/banner-ads/upload", methods=["POST"])
def upload_banner_ad_image():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401

    image = request.files.get("image")
    if not image or not image.filename:
        return jsonify({"error": "Banner image is required"}), 400

    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/avif"}
    if image.mimetype not in allowed_types:
        return jsonify({"error": "Use a JPEG, PNG, WEBP, or AVIF image"}), 400
    if request.content_length and request.content_length > 5 * 1024 * 1024:
        return jsonify({"error": "Banner image must be smaller than 5MB"}), 400

    try:
        url = upload_image(image.stream, "trollz/seller/banner-ads")
        return jsonify({"success": True, "data": {"url": url}})
    except Exception as exc:
        print("Unable to upload seller banner image:", exc)
        return jsonify({"error": "Banner image upload failed"}), 502


@seller_bp.route("/banner-ads/checkout", methods=["POST"])
def create_banner_ad_checkout():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401
    ensure_seller_tables()

    data = request.get_json(silent=True) or {}
    plan_code = str(data.get("plan_code") or "").strip().lower()
    image_url = valid_http_url(data.get("image_url"))
    target_url = valid_http_url(data.get("target_url")) if data.get("target_url") else None
    if not plan_code:
        return jsonify({"error": "Choose an advertising period"}), 400
    if not image_url:
        return jsonify({"error": "Upload a banner image before paying"}), 400
    if data.get("target_url") and not target_url:
        return jsonify({"error": "The destination URL must start with http:// or https://"}), 400

    plan = query_one(
        "SELECT code, name, duration_days, price FROM seller_banner_ad_plans WHERE code=%s AND is_active=1 LIMIT 1",
        (plan_code,),
    )
    if not plan:
        return jsonify({"error": "That advertising period is unavailable"}), 400
    amount = float(plan.get("price") or 0)
    if amount <= 0:
        return jsonify({"error": "This advertising period has not been priced by the admin yet"}), 409

    seller = query_one("SELECT id, name, email, phone FROM users WHERE id=%s AND role='Seller' LIMIT 1", (seller_id,))
    secret_key = os.getenv("FLUTTERWAVE_SECRET_KEY")
    if not seller or not secret_key:
        return jsonify({"error": "Banner advertising payments are not configured yet"}), 503

    tx_ref = f"TROLLZ_BANNER_{seller_id}_{uuid.uuid4().hex}"
    execute(
        """
        INSERT INTO seller_banner_ads
            (seller_id, plan_code, amount, image_url, target_url, tx_ref, payment_status, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'pending', 'pending')
        """,
        (seller_id, plan_code, amount, image_url, target_url, tx_ref),
    )

    redirect_url = os.getenv(
        "SELLER_BANNER_AD_REDIRECT_URL",
        "https://seller.trollzstore.com.ng/dashboard/banner-ads/payment",
    )
    try:
        response = requests.post(
            "https://api.flutterwave.com/v3/payments",
            headers={"Authorization": f"Bearer {secret_key}", "Content-Type": "application/json"},
            json={
                "tx_ref": tx_ref,
                "amount": amount,
                "currency": "NGN",
                "redirect_url": redirect_url,
                "customer": {
                    "email": seller.get("email"),
                    "name": seller.get("name"),
                    "phonenumber": seller.get("phone") or "",
                },
                "customizations": {
                    "title": "Trollz Store Seller Banner Ad",
                    "description": f"{plan.get('name')} homepage banner advertising",
                },
            },
            timeout=20,
        )
        payload = response.json()
    except Exception as exc:
        execute("UPDATE seller_banner_ads SET payment_status='failed', status='failed' WHERE tx_ref=%s", (tx_ref,))
        print("Unable to initialize seller banner payment:", exc)
        return jsonify({"error": "Unable to start payment right now"}), 502

    if response.status_code >= 400 or payload.get("status") != "success" or not payload.get("data", {}).get("link"):
        execute("UPDATE seller_banner_ads SET payment_status='failed', status='failed' WHERE tx_ref=%s", (tx_ref,))
        return jsonify({"error": payload.get("message") or "Unable to start payment right now"}), 502

    return jsonify({
        "success": True,
        "data": {"payment_link": payload["data"]["link"], "tx_ref": tx_ref, "amount": amount},
    })


@seller_bp.route("/banner-ads/verify", methods=["POST"])
def verify_banner_ad_payment():
    seller_id = get_seller_id()
    if not seller_id:
        return jsonify({"error": "Unauthorized"}), 401
    ensure_seller_tables()

    data = request.get_json(silent=True) or {}
    tx_ref = str(data.get("tx_ref") or "").strip()
    if not tx_ref:
        return jsonify({"error": "Payment reference is required"}), 400

    ad = query_one(
        "SELECT * FROM seller_banner_ads WHERE tx_ref=%s AND seller_id=%s LIMIT 1",
        (tx_ref, seller_id),
    )
    if not ad:
        return jsonify({"error": "Banner ad payment was not found"}), 404
    if ad.get("payment_status") == "paid" and ad.get("status") == "active":
        return jsonify({"success": True, "data": {"ad": serialize_banner_ad(ad)}})

    secret_key = os.getenv("FLUTTERWAVE_SECRET_KEY")
    if not secret_key:
        return jsonify({"error": "Payment verification is not configured"}), 503
    try:
        response = requests.get(
            "https://api.flutterwave.com/v3/transactions/verify_by_reference",
            params={"tx_ref": tx_ref},
            headers={"Authorization": f"Bearer {secret_key}"},
            timeout=20,
        )
        payload = response.json()
    except Exception as exc:
        print("Unable to verify seller banner payment:", exc)
        return jsonify({"error": "Payment verification is temporarily unavailable"}), 502

    transaction = payload.get("data") if payload.get("status") == "success" else None
    valid = bool(
        transaction
        and transaction.get("status") == "successful"
        and transaction.get("tx_ref") == tx_ref
        and str(transaction.get("currency") or "").upper() == "NGN"
        and float(transaction.get("amount") or 0) >= float(ad.get("amount") or 0)
    )
    if not valid:
        return jsonify({"error": "Payment has not been completed or could not be verified"}), 400

    plan = query_one("SELECT duration_days FROM seller_banner_ad_plans WHERE code=%s LIMIT 1", (ad.get("plan_code"),))
    duration_days = int((plan or {}).get("duration_days") or 30)
    starts_at = datetime.utcnow()
    expires_at = starts_at + timedelta(days=duration_days)
    execute(
        """
        UPDATE seller_banner_ads
        SET transaction_id=%s, payment_status='paid', status='active', starts_at=%s, expires_at=%s
        WHERE id=%s AND seller_id=%s
        """,
        (str(transaction.get("id") or ""), starts_at, expires_at, ad.get("id"), seller_id),
    )
    updated = query_one("SELECT * FROM seller_banner_ads WHERE id=%s LIMIT 1", (ad.get("id"),))
    return jsonify({"success": True, "data": {"ad": serialize_banner_ad(updated)}})


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
