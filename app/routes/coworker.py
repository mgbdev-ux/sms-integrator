import time
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify

from ..db import get_db
from ..security import verify_coworker_password, generate_token, verify_token, get_bearer_token
from ..config import Config
from ..extensions import limiter

coworker_bp = Blueprint("coworker", __name__, url_prefix="/api")


def _require_coworker():
    token = get_bearer_token(request)
    username = verify_token(token)
    if not username:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    return username, None


@coworker_bp.route("/login", methods=["POST"])
@limiter.limit("5 per minute; 30 per hour")
def coworker_login():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")

    user = verify_coworker_password(username, password or "")
    if user:
        token = generate_token(username)
        return (
            jsonify(
                {
                    "token": token,
                    "username": user["username"],
                    "name": user["name"],
                    "my_number": Config.MY_NUMBER,
                }
            ),
            200,
        )
    return jsonify({"error": "Invalid user credentials"}), 401


@coworker_bp.route("/inbox", methods=["GET"])
def coworker_inbox():
    username, err = _require_coworker()
    if err:
        return err

    conn = get_db()
    # Only this coworker's own sent messages and replies routed to them -
    # coworkers should never see each other's conversations.
    rows = conn.execute(
        "SELECT * FROM messages WHERE owner = ? ORDER BY time DESC, id DESC LIMIT 200",
        (username,),
    ).fetchall()
    conn.close()
    return jsonify({"messages": [dict(r) for r in rows]})


@coworker_bp.route("/send", methods=["POST"])
def coworker_send_sms():
    username, err = _require_coworker()
    if err:
        return err

    data = request.json or {}
    to = data.get("to")
    text = data.get("text")

    if not to or not text:
        return jsonify({"error": "Receiver and message are required"}), 400

    conn = get_db()
    
    # Confirm user existence
    user_row = conn.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone()
    if not user_row:
        conn.close()
        return jsonify({"error": "User profile not found"}), 404

    msg_id = f"MSG-{int(time.time() * 1000)}"
    time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """
        INSERT INTO messages (id, direction, sender, recipient, text, time, status, owner)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (msg_id, "out", username, to, text, time_str, "queued", username),
    )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message_id": msg_id}), 200
