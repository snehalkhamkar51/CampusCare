"""CampusCare Flask application."""

import os
import re
import secrets
from functools import wraps

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import (
    VALID_CATEGORIES,
    VALID_PRIORITIES,
    VALID_ROLES,
    VALID_STATUSES,
    create_user,
    email_exists,
    generate_complaint_id,
    get_db as connect_db,
    get_user_by_id,
    get_user_by_username,
    init_db,
    now_iso,
    username_exists,
)

PER_PAGE = 10


def create_app(database_path=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "dev-secret-change-in-production"
    )
    app.config["DATABASE_PATH"] = database_path or os.environ.get(
        "DATABASE_PATH", os.path.join("instance", "campuscare.db")
    )
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = (
        os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    )

    init_db(app.config["DATABASE_PATH"])

    def db():
        return connect_db(current_app.config["DATABASE_PATH"])

    def current_user():
        user_id = session.get("user_id")
        if not user_id:
            return None
        return get_user_by_id(current_app.config["DATABASE_PATH"], user_id)

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if current_user() is None:
                flash("Please log in to continue.", "error")
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)

        return wrapped

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                flash("Please log in to continue.", "error")
                return redirect(url_for("login", next=request.path))
            if user["role"] != "admin":
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    def ensure_csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    def validate_csrf():
        token = request.form.get("csrf_token", "")
        return bool(token) and token == session.get("csrf_token")

    def csrf_protect(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not validate_csrf():
                abort(400)
            return view(*args, **kwargs)

        return wrapped

    @app.context_processor
    def inject_globals():
        return {
            "categories": VALID_CATEGORIES,
            "priorities": VALID_PRIORITIES,
            "statuses": VALID_STATUSES,
            "current_user": current_user(),
            "csrf_token": ensure_csrf_token(),
        }

    @app.before_request
    def load_user():
        g.user = current_user()

    def get_counts(user=None):
        conn = db()
        try:
            if user and user["role"] == "student":
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS c FROM complaints WHERE user_id = ? GROUP BY status",
                    (user["id"],),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS c FROM complaints GROUP BY status"
                ).fetchall()
        finally:
            conn.close()
        counts = {"total": 0, "pending": 0, "in_progress": 0, "resolved": 0}
        for row in rows:
            status = row["status"]
            c = row["c"]
            counts["total"] += c
            if status == "Pending":
                counts["pending"] = c
            elif status == "In Progress":
                counts["in_progress"] = c
            elif status == "Resolved":
                counts["resolved"] = c
        return counts

    def fetch_complaint_by_public_id(public_id):
        conn = db()
        try:
            return conn.execute(
                "SELECT * FROM complaints WHERE complaint_id = ?", (public_id,)
            ).fetchone()
        finally:
            conn.close()

    def list_complaints(user, page=1):
        status_filter = request.args.get("status", "").strip()
        priority_filter = request.args.get("priority", "").strip()
        category_filter = request.args.get("category", "").strip()
        search = request.args.get("q", "").strip()

        where = []
        params = []

        if user["role"] == "student":
            where.append("user_id = ?")
            params.append(user["id"])

        if status_filter in VALID_STATUSES:
            where.append("status = ?")
            params.append(status_filter)
        if priority_filter in VALID_PRIORITIES:
            where.append("priority = ?")
            params.append(priority_filter)
        if category_filter in VALID_CATEGORIES:
            where.append("category = ?")
            params.append(category_filter)
        if search:
            where.append("(complaint_id LIKE ? OR title LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        where_sql = " AND ".join(where) if where else "1=1"

        conn = db()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM complaints WHERE {where_sql}", params
            ).fetchone()["c"]
            offset = (page - 1) * PER_PAGE
            rows = conn.execute(
                f"SELECT * FROM complaints WHERE {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [PER_PAGE, offset],
            ).fetchall()
        finally:
            conn.close()

        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        filters = {
            "status": status_filter,
            "priority": priority_filter,
            "category": category_filter,
            "q": search,
        }
        return rows, total, total_pages, filters

    @app.route("/health")
    def health():
        return jsonify({"status": "healthy", "application": "CampusCare"})

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user() is not None:
            return redirect(url_for("dashboard"))

        form = {"username": "", "email": ""}
        errors = []

        if request.method == "POST":
            if not validate_csrf():
                abort(400)
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")

            form["username"] = username
            form["email"] = email

            if not re.match(r"^[A-Za-z0-9_]{3,30}$", username):
                errors.append("Username must be 3-30 characters (letters, numbers, underscore).")
            if "@" not in email or "." not in email.split("@")[-1]:
                errors.append("Please enter a valid email address.")
            if len(password) < 8:
                errors.append("Password must be at least 8 characters.")
            if password != confirm:
                errors.append("Passwords do not match.")
            if username and username_exists(app.config["DATABASE_PATH"], username):
                errors.append("That username is already taken.")
            if email and email_exists(app.config["DATABASE_PATH"], email):
                errors.append("That email is already registered.")

            if not errors:
                password_hash = generate_password_hash(password)
                create_user(
                    app.config["DATABASE_PATH"],
                    username,
                    email,
                    password_hash,
                    "student",
                )
                flash("Registration successful. Please log in.", "success")
                return redirect(url_for("login"))

        return render_template("register.html", form=form, errors=errors)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user() is not None:
            return redirect(url_for("dashboard"))

        form = {"username": ""}
        if request.method == "POST":
            if not validate_csrf():
                abort(400)
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            form["username"] = username

            user = get_user_by_username(app.config["DATABASE_PATH"], username)
            if user is not None and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_id"] = user["id"]
                session["csrf_token"] = secrets.token_urlsafe(32)
                flash(f"Welcome back, {user['username']}.", "success")
                next_url = request.args.get("next") or request.form.get("next")
                if next_url and next_url.startswith("/"):
                    return redirect(next_url)
                return redirect(url_for("dashboard"))
            flash("Invalid username or password.", "error")

        return render_template("login.html", form=form)

    @app.route("/logout", methods=["POST"])
    @csrf_protect
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        user = current_user()
        counts = get_counts(user)
        conn = db()
        try:
            if user["role"] == "student":
                recent = conn.execute(
                    "SELECT * FROM complaints WHERE user_id = ? ORDER BY id DESC LIMIT 5",
                    (user["id"],),
                ).fetchall()
            else:
                recent = conn.execute(
                    "SELECT * FROM complaints ORDER BY id DESC LIMIT 5"
                ).fetchall()
        finally:
            conn.close()
        return render_template(
            "index.html",
            counts=counts,
            recent=recent,
            user=user,
        )

    @app.route("/complaints")
    @login_required
    def complaints():
        user = current_user()
        page = max(1, request.args.get("page", 1, type=int))
        rows, total, total_pages, filters = list_complaints(user, page)
        return render_template(
            "complaints.html",
            complaints=rows,
            total=total,
            page=page,
            total_pages=total_pages,
            filters=filters,
            user=user,
        )

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        user = current_user()
        page = max(1, request.args.get("page", 1, type=int))
        rows, total, total_pages, filters = list_complaints(user, page)
        counts = get_counts(None)
        return render_template(
            "admin.html",
            complaints=rows,
            total=total,
            page=page,
            total_pages=total_pages,
            filters=filters,
            counts=counts,
            user=user,
        )

    @app.route("/complaints/new", methods=["GET", "POST"])
    @login_required
    def new_complaint():
        user = current_user()
        form = {
            "category": "",
            "title": "",
            "description": "",
            "priority": "Medium",
        }
        errors = []

        if request.method == "POST":
            if not validate_csrf():
                abort(400)
            form["category"] = request.form.get("category", "").strip()
            form["title"] = request.form.get("title", "").strip()
            form["description"] = request.form.get("description", "").strip()
            form["priority"] = request.form.get("priority", "").strip()

            if form["category"] not in VALID_CATEGORIES:
                errors.append("Please select a valid category.")
            if not form["title"]:
                errors.append("Title is required.")
            if not form["description"]:
                errors.append("Description is required.")
            if form["priority"] not in VALID_PRIORITIES:
                errors.append("Please select a valid priority.")

            if not errors:
                conn = db()
                try:
                    complaint_id = generate_complaint_id(conn)
                    conn.execute(
                        """
                        INSERT INTO complaints
                        (complaint_id, category, title, description, priority, status, user_id, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            complaint_id,
                            form["category"],
                            form["title"],
                            form["description"],
                            form["priority"],
                            "Pending",
                            user["id"],
                            now_iso(),
                            now_iso(),
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
                flash(
                    f"Complaint submitted successfully. Your complaint ID is {complaint_id}.",
                    "success",
                )
                return redirect(url_for("complaints"))

        return render_template("new_complaint.html", form=form, errors=errors, user=user)

    @app.route("/complaints/<complaint_id>")
    @login_required
    def complaint_detail(complaint_id):
        user = current_user()
        complaint = fetch_complaint_by_public_id(complaint_id)
        if complaint is None:
            abort(404)
        if user["role"] != "admin" and complaint["user_id"] != user["id"]:
            abort(403)
        return render_template(
            "complaint_detail.html", complaint=complaint, user=user
        )

    @app.route("/admin/complaints/<int:complaint_pk>/status", methods=["POST"])
    @admin_required
    @csrf_protect
    def update_status(complaint_pk):
        new_status = request.form.get("status", "").strip()
        if new_status not in VALID_STATUSES:
            flash("Invalid status value.", "error")
            return redirect(url_for("admin_dashboard"))

        conn = db()
        try:
            row = conn.execute(
                "SELECT id FROM complaints WHERE id = ?", (complaint_pk,)
            ).fetchone()
            if row is None:
                abort(404)
            conn.execute(
                "UPDATE complaints SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now_iso(), complaint_pk),
            )
            conn.commit()
        finally:
            conn.close()

        flash("Complaint status updated.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403, message="Access denied."), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404, message="Page not found."), 404

    @app.errorhandler(400)
    def bad_request(_):
        return render_template("error.html", code=400, message="Bad request."), 400

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
