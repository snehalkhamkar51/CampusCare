"""CampusCare Flask application."""

import os

from flask import (
    Flask,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from database import (
    VALID_CATEGORIES,
    VALID_PRIORITIES,
    VALID_STATUSES,
    generate_complaint_id,
    get_db,
    init_db,
    now_iso,
)


def create_app(database_path=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "dev-secret-change-in-production"
    )
    app.config["DATABASE_PATH"] = database_path or os.environ.get(
        "DATABASE_PATH", os.path.join("instance", "campuscare.db")
    )

    init_db(app.config["DATABASE_PATH"])

    @app.context_processor
    def inject_globals():
        return {
            "categories": VALID_CATEGORIES,
            "priorities": VALID_PRIORITIES,
            "statuses": VALID_STATUSES,
        }

    def db():
        return get_db(current_app.config["DATABASE_PATH"])

    def get_counts():
        conn = db()
        try:
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

    @app.route("/")
    def dashboard():
        conn = db()
        try:
            recent = conn.execute(
                "SELECT * FROM complaints ORDER BY id DESC LIMIT 5"
            ).fetchall()
        finally:
            conn.close()
        return render_template(
            "index.html", counts=get_counts(), recent=recent
        )

    @app.route("/complaints")
    def complaints():
        status_filter = request.args.get("status", "").strip()
        priority_filter = request.args.get("priority", "").strip()

        query = "SELECT * FROM complaints WHERE 1=1"
        params = []
        if status_filter in VALID_STATUSES:
            query += " AND status = ?"
            params.append(status_filter)
        if priority_filter in VALID_PRIORITIES:
            query += " AND priority = ?"
            params.append(priority_filter)
        query += " ORDER BY id DESC"

        conn = db()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        return render_template(
            "complaints.html",
            complaints=rows,
            status_filter=status_filter,
            priority_filter=priority_filter,
        )

    @app.route("/complaints/new", methods=["GET", "POST"])
    def new_complaint():
        form = {
            "category": "",
            "title": "",
            "description": "",
            "priority": "Medium",
        }
        errors = []

        if request.method == "POST":
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
                        (complaint_id, category, title, description, priority, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            complaint_id,
                            form["category"],
                            form["title"],
                            form["description"],
                            form["priority"],
                            "Pending",
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

        return render_template(
            "new_complaint.html", form=form, errors=errors
        )

    @app.route("/health")
    def health():
        return jsonify({"status": "healthy", "application": "CampusCare"})

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
