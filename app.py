import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.products import products_bp
from routes.categories import categories_bp
from routes.orders import orders_bp
from routes.support import support_bp
from routes.users import users_bp
from routes.delivery import delivery_bp
from routes.export import export_bp
from routes.flash_sale import flash_sale_bp
from routes.upload import upload_bp
from routes.seller import seller_bp, initialize_seller_module

app = Flask(__name__)
CORS(app, origins="*")

API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")

@app.before_request
def check_api_key():
    # Skip preflight
    if request.method == "OPTIONS":
        return
    if request.path.startswith("/api/seller") or request.path == "/api/health":
        return
    if request.method == "GET" and request.path.startswith("/api/categories"):
        return
    key = request.headers.get("X-API-Key", "")
    if key != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
app.register_blueprint(products_bp, url_prefix="/api/products")
app.register_blueprint(categories_bp, url_prefix="/api/categories")
app.register_blueprint(orders_bp, url_prefix="/api/orders")
app.register_blueprint(support_bp, url_prefix="/api/support")
app.register_blueprint(users_bp, url_prefix="/api/users")
app.register_blueprint(delivery_bp, url_prefix="/api/delivery")
app.register_blueprint(export_bp, url_prefix="/api/export")
app.register_blueprint(flash_sale_bp, url_prefix="/api/flash-sale")
app.register_blueprint(upload_bp, url_prefix="/api/upload")
app.register_blueprint(seller_bp, url_prefix="/api/seller")

# Initialize the seller module at startup instead of using Flask 3.x deprecated hooks.
initialize_seller_module()

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(debug=False)
