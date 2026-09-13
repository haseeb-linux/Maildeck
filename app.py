"""
app.py
Main Flask application: routes, auth, dashboard, compose, templates,
history, settings, scheduling and CSV/PDF export.
"""

import os
import io
import csv
import logging
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    jsonify, send_file, Response, session
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from werkzeug.utils import secure_filename
from apscheduler.schedulers.background import BackgroundScheduler
import pandas as pd

from config import config_map
from models import db, User, EmailLog, Template, ScheduledEmail
from email_handler import EmailHandler

# ---------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------
env = os.environ.get("FLASK_ENV", "development")
app = Flask(__name__)
app.config.from_object(config_map.get(env, config_map["default"]))

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["ATTACHMENT_FOLDER"], exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"

scheduler = BackgroundScheduler()
scheduler.start()


def get_email_handler():
    return EmailHandler(
        sender_email=app.config["SENDER_EMAIL"],
        app_password=app.config["APP_PASSWORD"],
        smtp_server=app.config["SMTP_SERVER"],
        smtp_port=app.config["SMTP_PORT"],
    )


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def allowed_file(filename, allowed_set):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set


# ---------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("signup"))

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash("Username or email already exists.", "danger")
            return redirect(url_for("signup"))

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    total_sent = EmailLog.query.filter_by(status="sent").count()
    total_failed = EmailLog.query.filter_by(status="failed").count()
    total_pending = EmailLog.query.filter_by(status="pending").count()
    total_scheduled = ScheduledEmail.query.filter_by(status="pending").count()
    recent_logs = EmailLog.query.order_by(EmailLog.timestamp.desc()).limit(8).all()
    total_templates = Template.query.count()

    return render_template(
        "dashboard.html",
        total_sent=total_sent,
        total_failed=total_failed,
        total_pending=total_pending,
        total_scheduled=total_scheduled,
        total_templates=total_templates,
        recent_logs=recent_logs,
    )


# ---------------------------------------------------------------------
# Compose / Send
# ---------------------------------------------------------------------
@app.route("/compose", methods=["GET", "POST"])
@login_required
def compose():
    templates_list = Template.query.order_by(Template.created_at.desc()).all()

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()
        recipients_raw = request.form.get("recipients", "").strip()
        send_mode = request.form.get("send_mode", "now")

        if not subject or not body:
            flash("Subject and body are required.", "danger")
            return redirect(url_for("compose"))

        # Collect recipients: textarea (comma/newline separated) + optional CSV upload
        recipients = []
        if recipients_raw:
            parts = [p.strip() for p in recipients_raw.replace("\n", ",").split(",")]
            recipients.extend([{"email": p} for p in parts if p])

        csv_file = request.files.get("csv_file")
        if csv_file and csv_file.filename and allowed_file(csv_file.filename, app.config["ALLOWED_CSV_EXTENSIONS"]):
            filename = secure_filename(csv_file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            csv_file.save(filepath)
            try:
                df = pd.read_csv(filepath)
                df.columns = [c.strip().lower() for c in df.columns]
                if "email" not in df.columns:
                    flash("CSV must contain an 'email' column.", "danger")
                    return redirect(url_for("compose"))
                for _, row in df.iterrows():
                    recipients.append({k: str(v) for k, v in row.to_dict().items() if pd.notna(v)})
            except Exception as e:
                flash(f"Could not read CSV: {e}", "danger")
                return redirect(url_for("compose"))

        if not recipients:
            flash("Please provide at least one recipient.", "danger")
            return redirect(url_for("compose"))

        # Attachments
        attachment_paths = []
        for file in request.files.getlist("attachments"):
            if file and file.filename and allowed_file(file.filename, app.config["ALLOWED_ATTACHMENT_EXTENSIONS"]):
                filename = secure_filename(file.filename)
                path = os.path.join(app.config["ATTACHMENT_FOLDER"], f"{datetime.utcnow().timestamp()}_{filename}")
                file.save(path)
                attachment_paths.append(path)

        # ---- Scheduled send ----
        if send_mode == "schedule":
            scheduled_time_str = request.form.get("scheduled_time")
            if not scheduled_time_str:
                flash("Please choose a date/time to schedule.", "danger")
                return redirect(url_for("compose"))
            scheduled_time = datetime.fromisoformat(scheduled_time_str)

            recipients_str = ",".join([r["email"] for r in recipients])
            job = ScheduledEmail(
                user_id=current_user.id,
                recipients=recipients_str,
                subject=subject,
                body=body,
                attachment_path=";".join(attachment_paths) if attachment_paths else None,
                scheduled_time=scheduled_time,
                status="pending",
            )
            db.session.add(job)
            db.session.commit()

            scheduler.add_job(
                func=send_scheduled_job,
                trigger="date",
                run_date=scheduled_time,
                args=[job.id],
                id=f"job_{job.id}",
                replace_existing=True,
            )
            job.job_id = f"job_{job.id}"
            db.session.commit()

            flash(f"Email scheduled for {scheduled_time.strftime('%Y-%m-%d %H:%M')}.", "success")
            return redirect(url_for("dashboard"))

        # ---- Send now ----
        handler = get_email_handler()
        results = handler.send_bulk(
            recipients, subject, body,
            attachments=attachment_paths,
            tracking_base_url=request.url_root.rstrip("/"),
        )

        for r in results:
            log = EmailLog(
                user_id=current_user.id,
                recipient=r["email"],
                subject=r["subject"],
                body=r["body"],
                status="sent" if r["success"] else "failed",
                error_message=r["error"],
                tracking_id=r["tracking_id"],
            )
            db.session.add(log)
        db.session.commit()

        success_count = sum(1 for r in results if r["success"])
        flash(f"Sent {success_count}/{len(results)} emails successfully.", "success" if success_count else "danger")
        return redirect(url_for("history"))

    return render_template("compose.html", templates_list=templates_list)


def send_scheduled_job(job_id):
    """Runs inside APScheduler at the scheduled time."""
    with app.app_context():
        job = ScheduledEmail.query.get(job_id)
        if not job or job.status != "pending":
            return
        handler = get_email_handler()
        recipients = [{"email": e.strip()} for e in job.recipients.split(",") if e.strip()]
        attachments = job.attachment_path.split(";") if job.attachment_path else []

        results = handler.send_bulk(recipients, job.subject, job.body, attachments=attachments)
        for r in results:
            log = EmailLog(
                user_id=job.user_id,
                recipient=r["email"],
                subject=r["subject"],
                body=r["body"],
                status="sent" if r["success"] else "failed",
                error_message=r["error"],
                tracking_id=r["tracking_id"],
            )
            db.session.add(log)

        job.status = "sent"
        db.session.commit()
        logger.info("Scheduled job %s executed.", job_id)


@app.route("/send-test", methods=["POST"])
@login_required
def send_test():
    to_email = request.form.get("test_email", "").strip()
    if not to_email:
        return jsonify({"success": False, "message": "Please provide an email address."}), 400

    handler = get_email_handler()
    success, error = handler.send_test_email(to_email)
    if success:
        return jsonify({"success": True, "message": f"Test email sent to {to_email}!"})
    return jsonify({"success": False, "message": error}), 500


# ---------------------------------------------------------------------
# Templates CRUD
# ---------------------------------------------------------------------
@app.route("/templates", methods=["GET", "POST"])
@login_required
def templates_page():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()

        if not name or not subject or not body:
            flash("All template fields are required.", "danger")
        else:
            t = Template(user_id=current_user.id, name=name, subject=subject, body=body)
            db.session.add(t)
            db.session.commit()
            flash("Template saved.", "success")
        return redirect(url_for("templates_page"))

    all_templates = Template.query.order_by(Template.created_at.desc()).all()
    return render_template("templates.html", templates_list=all_templates)


@app.route("/templates/delete/<int:template_id>", methods=["POST"])
@login_required
def delete_template(template_id):
    t = Template.query.get_or_404(template_id)
    db.session.delete(t)
    db.session.commit()
    flash("Template deleted.", "info")
    return redirect(url_for("templates_page"))


@app.route("/templates/<int:template_id>/json")
@login_required
def template_json(template_id):
    t = Template.query.get_or_404(template_id)
    return jsonify({"subject": t.subject, "body": t.body})


# ---------------------------------------------------------------------
# History
# ---------------------------------------------------------------------
@app.route("/history")
@login_required
def history():
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "all")

    query = EmailLog.query
    if status_filter != "all":
        query = query.filter_by(status=status_filter)

    pagination = query.order_by(EmailLog.timestamp.desc()).paginate(
        page=page, per_page=app.config["LOGS_PER_PAGE"], error_out=False
    )
    return render_template("history.html", logs=pagination.items, pagination=pagination, status_filter=status_filter)


@app.route("/history/export/csv")
@login_required
def export_csv():
    logs = EmailLog.query.order_by(EmailLog.timestamp.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Recipient", "Subject", "Status", "Error", "Opened", "Timestamp"])
    for log in logs:
        writer.writerow([log.recipient, log.subject, log.status, log.error_message or "",
                          "Yes" if log.opened else "No", log.timestamp.strftime("%Y-%m-%d %H:%M:%S")])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=email_history.csv"
    return response


@app.route("/history/export/pdf")
@login_required
def export_pdf():
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet

    logs = EmailLog.query.order_by(EmailLog.timestamp.desc()).all()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    styles = getSampleStyleSheet()

    data = [["Recipient", "Subject", "Status", "Timestamp"]]
    for log in logs:
        data.append([log.recipient, log.subject[:40], log.status, log.timestamp.strftime("%Y-%m-%d %H:%M")])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4f46e5")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
    ]))

    elements = [Paragraph("Email History Report", styles["Title"]), table]
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="email_history.pdf", mimetype="application/pdf")


# ---------------------------------------------------------------------
# Open-rate tracking pixel
# ---------------------------------------------------------------------
@app.route("/track/open/<tracking_id>")
def track_open(tracking_id):
    log = EmailLog.query.filter_by(tracking_id=tracking_id).first()
    if log and not log.opened:
        log.opened = True
        db.session.commit()
    # 1x1 transparent GIF
    pixel = (b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04'
              b'\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02'
              b'D\x01\x00;')
    return Response(pixel, mimetype="image/gif")


# ---------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------
@app.route("/settings")
@login_required
def settings():
    return render_template(
        "settings.html",
        sender_email=app.config["SENDER_EMAIL"],
        smtp_server=app.config["SMTP_SERVER"],
        smtp_port=app.config["SMTP_PORT"],
    )


# ---------------------------------------------------------------------
# Theme toggle (dark/light stored in session)
# ---------------------------------------------------------------------
@app.route("/toggle-theme", methods=["POST"])
def toggle_theme():
    current = session.get("theme", "light")
    session["theme"] = "dark" if current == "light" else "light"
    return jsonify({"theme": session["theme"]})


@app.context_processor
def inject_theme():
    return {"theme": session.get("theme", "light")}


# ---------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    logger.exception("Server error: %s", e)
    return render_template("500.html"), 500


# ---------------------------------------------------------------------
# CLI: init-db
# ---------------------------------------------------------------------
@app.cli.command("init-db")
def init_db():
    """Initialise the database: flask init-db"""
    db.create_all()
    print("Database initialised.")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=app.config["DEBUG"], port=int(os.environ.get("PORT", 5000)))
