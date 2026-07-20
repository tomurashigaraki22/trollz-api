from flask import Blueprint, request, jsonify
from lib.cloudinary_helper import upload_image

upload_bp = Blueprint("upload", __name__)

@upload_bp.route("", methods=["POST"])
def upload():
    file = request.files.get("file")
    folder = request.form.get("folder", "trollz")
    if not file:
        return jsonify({"error": "No file"}), 400
    url = upload_image(file.stream, folder)
    return jsonify({"url": url})
