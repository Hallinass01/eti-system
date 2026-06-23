from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, send_file, Response
from werkzeug.utils import secure_filename
from datetime import datetime
from functools import wraps
import os
import json
import uuid
import shutil
import zipfile
from io import BytesIO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Safe storage path:
# - Works now using local project data folder.
# - Later, after Render disk is mounted, set PERSISTENT_DIR=/var/data.
PERSISTENT_DIR = os.environ.get(
    "PERSISTENT_DIR",
    os.path.join(BASE_DIR, "data")
)

UPLOAD_FOLDER = os.path.join(PERSISTENT_DIR, "uploads")
CASE_DIR = os.path.join(PERSISTENT_DIR, "cases")
REPORT_DIR = os.path.join(PERSISTENT_DIR, "reports")
CONFIG_DIR = os.path.join(BASE_DIR, "config")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CASE_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 500


# ----------------------------
# ETI INTAKE PROTECTION SETTINGS
# ----------------------------

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic", "heif"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "m4v", "avi", "webm"}

INTAKE_ACCESS_CODE = os.environ.get("INTAKE_ACCESS_CODE", "ETI-REVIEW-2026")

# Admin protection for Terrain Desk / case files
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ETI-ADMIN-2026")

SPAM_WORDS = [
    "btc",
    "bitcoin",
    "crypto",
    "wallet",
    "transaction id",
    "mined",
    "mining",
    "telegra.ph",
    "telegram",
    "download full case package",
    "airdrop",
    "claim reward",
    "investment",
    "forex",
    "casino",
    "viagra",
    "loan offer",
    "seo backlinks",
    "rank your website",
]


# ----------------------------
# ADMIN PASSWORD PROTECTION
# ----------------------------

def check_admin_auth(auth):
    return (
        auth
        and auth.username == ADMIN_USERNAME
        and auth.password == ADMIN_PASSWORD
    )


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth = request.authorization

        if not check_admin_auth(auth):
            return Response(
                "Admin login required.",
                401,
                {"WWW-Authenticate": 'Basic realm="ETI Terrain Desk"'}
            )

        return func(*args, **kwargs)

    return wrapper


# ----------------------------
# HELPER FUNCTIONS
# ----------------------------

def clean(value):
    return (value or "").strip()


def file_has_name(file_storage):
    return bool(file_storage and file_storage.filename and file_storage.filename.strip())


def get_extension(filename):
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def allowed_file(file_storage, allowed_extensions):
    if not file_has_name(file_storage):
        return False
    return get_extension(file_storage.filename) in allowed_extensions


def has_allowed_file(files, allowed_extensions):
    return any(allowed_file(f, allowed_extensions) for f in files)


def normalize_order_number(order_number):
    value = clean(order_number).upper()

    if value and not value.startswith("#") and value.replace("-", "").isdigit():
        value = "#" + value

    return value


def count_existing_submissions_for_order(order_number):
    """
    Counts how many existing ETI cases already use this Shopify order number.
    This does not block the submission. It gives visibility and flags multiples.
    """
    normalized_order = normalize_order_number(order_number)

    if not normalized_order or not os.path.isdir(CASE_DIR):
        return 0

    count = 0

    for existing_case_id in os.listdir(CASE_DIR):
        case_json = os.path.join(CASE_DIR, existing_case_id, "case.json")

        if not os.path.exists(case_json):
            continue

        try:
            with open(case_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        existing_order = normalize_order_number(data.get("shopify_order_number", ""))

        if existing_order == normalized_order:
            count += 1

    return count


def submission_text_for_spam_check(form):
    return " ".join([
        form.get("horse_name", ""),
        form.get("owner_name", ""),
        form.get("trainer_name", ""),
        form.get("owner_email", ""),
        form.get("owner_phone", ""),
        form.get("discipline", ""),
        form.get("breed", ""),
        form.get("location", ""),
        form.get("shopify_order_number", ""),
        form.get("primary_question", ""),
        form.get("primary_concern_rank", ""),
        form.get("issue_started", ""),
        form.get("changed_before_notes", ""),
        form.get("success_60_days", ""),
        form.get("urgency_level", ""),
        form.get("horse_story", ""),
        form.get("feed_program", ""),
        form.get("supplement_program", ""),
        form.get("water_notes", ""),
        form.get("travel_notes", ""),
        form.get("surface_notes", ""),
        form.get("turnout_notes", ""),
    ]).lower()


def looks_like_spam(form):
    combined_text = submission_text_for_spam_check(form)
    return any(word in combined_text for word in SPAM_WORDS)


def validate_real_case_submission():
    """
    Blocks empty bot submissions and obvious spam before any case folder is created.
    Returns: (is_valid, message)
    """

    honeypot = clean(request.form.get("website", ""))
    if honeypot:
        return False, "Spam rejected."

    intake_access_code = clean(request.form.get("intake_access_code", ""))
    if intake_access_code != INTAKE_ACCESS_CODE:
        return False, "Valid ETI intake access code required."

    horse_name = clean(request.form.get("horse_name", ""))
    owner_name = clean(request.form.get("owner_name", ""))
    owner_email = clean(request.form.get("owner_email", ""))
    owner_phone = clean(request.form.get("owner_phone", ""))
    shopify_order_number = clean(request.form.get("shopify_order_number", ""))
    primary_question = clean(request.form.get("primary_question", ""))
    horse_story = clean(request.form.get("horse_story", ""))

    eye_files = request.files.getlist("eye_photos")
    body_files = request.files.getlist("body_photos")
    video_files = request.files.getlist("videos")

    all_files = eye_files + body_files + video_files
    has_any_file = any(file_has_name(f) for f in all_files)

    has_valid_eye_photo = has_allowed_file(eye_files, ALLOWED_IMAGE_EXTENSIONS)
    has_valid_body_photo = has_allowed_file(body_files, ALLOWED_IMAGE_EXTENSIONS)
    has_valid_video = has_allowed_file(video_files, ALLOWED_VIDEO_EXTENSIONS)

    meaningful_text = [
        horse_name,
        owner_name,
        owner_email,
        owner_phone,
        shopify_order_number,
        primary_question,
        horse_story,
    ]

    if not any(meaningful_text) and not has_any_file:
        return False, "Empty submission rejected."

    if not shopify_order_number:
        return False, "Shopify order number required."

    if not owner_email and not owner_phone:
        return False, "Contact information required."

    if not horse_name:
        return False, "Horse name required."

    if not owner_name:
        return False, "Owner name required."

    if not primary_question and not horse_story:
        return False, "Primary concern or horse story required."

    if not (has_valid_eye_photo or has_valid_body_photo or has_valid_video):
        return False, "At least one valid photo or video is required."

    if looks_like_spam(request.form):
        return False, "Spam rejected."

    return True, "OK"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def make_case_id():
    return datetime.utcnow().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8]


def save_files(files, folder, allowed_extensions=None):
    saved = []
    os.makedirs(folder, exist_ok=True)

    for f in files:
        if not file_has_name(f):
            continue

        if allowed_extensions is not None and not allowed_file(f, allowed_extensions):
            print(f"Skipped disallowed upload: {f.filename}")
            continue

        filename = f"{uuid.uuid4().hex}_{secure_filename(f.filename)}"
        filepath = os.path.join(folder, filename)
        f.save(filepath)
        saved.append(filename)

    return saved


def compute_scores(form, scoring_template):
    symptoms = set(form.get("symptoms", []))
    scores = {"hydration": 2, "gut": 2, "muscle": 2, "metabolic": 2}

    if "Slow recovery" in symptoms:
        scores["hydration"] += 2
    if "Digestive instability" in symptoms:
        scores["gut"] += 3
    if "Stopping at fences" in symptoms:
        scores["muscle"] += 2
    if "Tight or anxious" in symptoms:
        scores["metabolic"] += 3

    result = {}

    for pillar, raw in scores.items():
        raw = min(raw, 10)
        band = "Stable"

        for span, label in scoring_template[pillar]["bands"].items():
            start, end = map(int, span.split("-"))
            if start <= raw <= end:
                band = label
                break

        result[pillar] = {"score": raw, "band": band}

    return result


def build_locked_sections(form):
    return {
        "Horse Identification and Presenting Concern":
            f"{form.get('horse_name','This horse')} submitted for review.",
        "Intake Summary":
            form.get("horse_story", ""),
        "Eye Image Review":
            f"{len(form['files']['eye_photos'])} eye photos submitted.",
        "Movement / Video Review":
            f"{len(form['files']['body_photos'])} body photos and {len(form['files']['videos'])} videos submitted.",
        "Terrain Interpretation":
            "Pattern suggests terrain imbalance requiring structured review.",
        "Progression Pattern":
            "Determine improving, plateauing, or regressing.",
        "What This Looks Like If Ignored":
            "May progress into greater inconsistency and breakdown.",
        "ETI Conclusion":
            "Full review pending.",
        "Care Team Guidance":
            "Direct practical notes for the owner, trainer, veterinarian, farrier, and care team.",
        "Next-Step Framework":
            "Immediate priorities, monitoring, follow-up."
    }


def write_report(case_id, form):
    report_path = os.path.join(REPORT_DIR, f"{case_id}.txt")
    files = form.get("files", {})

    lines = [
        "Equine Terrain Institute",
        "The New Science of the Modern Horse: The Terrain Revolution",
        "",
        "CASE INFORMATION",
        f"Case ID: {case_id}",
        f"Shopify Order Number: {form.get('shopify_order_number', '')}",
        f"Order Submission Number: {form.get('order_submission_number', '')}",
        f"Previous Submissions On This Order: {form.get('previous_order_submissions', '')}",
        f"Order Quantity Verification Flag: {form.get('order_submission_note', '')}",
        f"Submitted: {form.get('submitted_at', '')}",
        "",
        "HORSE INFORMATION",
        f"Horse: {form.get('horse_name', '')}",
        f"Discipline: {form.get('discipline', '')}",
        f"Breed: {form.get('breed', '')}",
        f"Age: {form.get('age', '')}",
        f"Sex: {form.get('sex', '')}",
        f"Location: {form.get('location', '')}",
        "",
        "OWNER / TRAINER INFORMATION",
        f"Owner: {form.get('owner_name', '')}",
        f"Trainer: {form.get('trainer_name', '')}",
        f"Owner Email: {form.get('owner_email', '')}",
        f"Owner Phone: {form.get('owner_phone', '')}",
        "",
        "PRIMARY CONCERN",
        form.get("primary_question", ""),
        "",
        "PRIMARY CONCERN CATEGORY",
        form.get("primary_concern_rank", ""),
        "",
        "TIMELINE",
        f"When This First Began: {form.get('issue_started', '')}",
        "",
        "WHAT CHANGED BEFORE THIS STARTED",
        ", ".join(form.get("changed_before", [])),
        "",
        "Change Notes:",
        form.get("changed_before_notes", ""),
        "",
        "60-DAY SUCCESS GOAL",
        form.get("success_60_days", ""),
        "",
        "URGENCY LEVEL",
        form.get("urgency_level", ""),
        "",
        "HORSE STORY",
        form.get("horse_story", ""),
        "",
        "MANAGEMENT NOTES",
        f"Feed Program: {form.get('feed_program', '')}",
        f"Supplement Program: {form.get('supplement_program', '')}",
        f"Water Notes: {form.get('water_notes', '')}",
        f"Travel Notes: {form.get('travel_notes', '')}",
        f"Surface Notes: {form.get('surface_notes', '')}",
        f"Turnout Notes: {form.get('turnout_notes', '')}",
        "",
        "SYMPTOMS / PATTERNS SELECTED",
        ", ".join(form.get("symptoms", [])),
        "",
        "REVIEW FLAGS",
        ", ".join(form.get("review_flags", [])),
        "",
        "MEDIA SUBMITTED",
        f"Eye Photos: {len(files.get('eye_photos', []))}",
        f"Body Photos: {len(files.get('body_photos', []))}",
        f"Videos: {len(files.get('videos', []))}",
        "",
        "SCORES",
    ]

    for pillar in ["hydration", "gut", "muscle", "metabolic"]:
        s = form["scores"][pillar]
        lines.append(f"- {pillar.title()}: {s['score']} ({s['band']})")

    lines.append("")

    for section, text in form["locked_sections"].items():
        lines.append(section)
        lines.append(text)
        lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ----------------------------
# PUBLIC ROUTES
# ----------------------------

@app.route("/", methods=["GET", "POST"])
def intake():
    if request.method == "POST":

        is_valid, message = validate_real_case_submission()

        if not is_valid:
            print(f"Rejected submission: {message}")
            return message, 400

        case_id = make_case_id()
        case_folder = os.path.join(CASE_DIR, case_id)
        uploads_folder = os.path.join(case_folder, "uploads")

        os.makedirs(case_folder, exist_ok=True)
        os.makedirs(uploads_folder, exist_ok=True)

        eye_paths = save_files(
            request.files.getlist("eye_photos"),
            uploads_folder,
            ALLOWED_IMAGE_EXTENSIONS
        )
        body_paths = save_files(
            request.files.getlist("body_photos"),
            uploads_folder,
            ALLOWED_IMAGE_EXTENSIONS
        )
        video_paths = save_files(
            request.files.getlist("videos"),
            uploads_folder,
            ALLOWED_VIDEO_EXTENSIONS
        )

        shopify_order_number = normalize_order_number(
            request.form.get("shopify_order_number", "")
        )

        previous_order_submissions = count_existing_submissions_for_order(
            shopify_order_number
        )

        order_submission_number = previous_order_submissions + 1
        order_duplicate_flag = order_submission_number > 1

        order_submission_note = ""
        if order_duplicate_flag:
            order_submission_note = (
                "Multiple submissions using same Shopify order number — "
                "verify purchased quantity before completing review."
            )

        form = {
            "submitted_at": datetime.utcnow().isoformat() + "Z",
            "horse_name": clean(request.form.get("horse_name", "")),
            "owner_name": clean(request.form.get("owner_name", "")),
            "trainer_name": clean(request.form.get("trainer_name", "")),
            "owner_email": clean(request.form.get("owner_email", "")),
            "owner_phone": clean(request.form.get("owner_phone", "")),
            "discipline": clean(request.form.get("discipline", "")),
            "breed": clean(request.form.get("breed", "")),
            "age": clean(request.form.get("age", "")),
            "sex": clean(request.form.get("sex", "")),
            "location": clean(request.form.get("location", "")),

            "shopify_order_number": shopify_order_number,
            "order_submission_number": order_submission_number,
            "previous_order_submissions": previous_order_submissions,
            "order_duplicate_flag": order_duplicate_flag,
            "order_submission_note": order_submission_note,

            "primary_question": clean(request.form.get("primary_question", "")),
            "primary_concern_rank": clean(request.form.get("primary_concern_rank", "")),
            "issue_started": clean(request.form.get("issue_started", "")),
            "changed_before": request.form.getlist("changed_before"),
            "changed_before_notes": clean(request.form.get("changed_before_notes", "")),
            "success_60_days": clean(request.form.get("success_60_days", "")),
            "urgency_level": clean(request.form.get("urgency_level", "")),
            "horse_story": clean(request.form.get("horse_story", "")),

            "feed_program": clean(request.form.get("feed_program", "")),
            "supplement_program": clean(request.form.get("supplement_program", "")),
            "water_notes": clean(request.form.get("water_notes", "")),
            "travel_notes": clean(request.form.get("travel_notes", "")),
            "surface_notes": clean(request.form.get("surface_notes", "")),
            "turnout_notes": clean(request.form.get("turnout_notes", "")),
            "symptoms": request.form.getlist("symptoms"),
            "review_flags": request.form.getlist("review_flags"),
            "status": "New",
            "priority": "Standard",
            "files": {
                "eye_photos": eye_paths,
                "body_photos": body_paths,
                "videos": video_paths
            }
        }

        scoring_template = load_json(os.path.join(CONFIG_DIR, "scoring_template.json"))
        form["scores"] = compute_scores(form, scoring_template)
        form["locked_sections"] = build_locked_sections(form)

        with open(os.path.join(case_folder, "case.json"), "w", encoding="utf-8") as f:
            json.dump(form, f, indent=2)

        write_report(case_id, form)

        # IMPORTANT:
        # Customer goes to success page only.
        # They do NOT see the internal case detail page.
        return redirect(url_for("success"))

    return render_template("index.html")


@app.route("/success")
def success():
    return render_template("success.html")


@app.route("/api/health")
def health():
    return jsonify({"ok": True})


# ----------------------------
# PROTECTED ADMIN ROUTES
# ----------------------------

@app.route("/terrain-desk")
@app.route("/cases")
@admin_required
def cases():
    selected_status = request.args.get("status", "").strip()
    search_query = request.args.get("q", "").strip().lower()

    rows = []
    counts = {
        "All": 0,
        "New": 0,
        "In Review": 0,
        "Report Drafted": 0,
        "Complete": 0,
    }

    if os.path.isdir(CASE_DIR):
        for case_id in sorted(os.listdir(CASE_DIR), reverse=True):
            case_json = os.path.join(CASE_DIR, case_id, "case.json")

            if os.path.exists(case_json):
                try:
                    with open(case_json, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception as e:
                    print(f"Failed loading case {case_id}: {e}")
                    continue

                case_status = data.get("status", "New")
                case_priority = data.get("priority", "Standard")
                horse_name = data.get("horse_name", "")
                owner_name = data.get("owner_name", "")
                trainer_name = data.get("trainer_name", "")
                discipline = data.get("discipline", "")
                primary_question = data.get("primary_question", "")

                shopify_order_number = data.get("shopify_order_number", "")
                order_submission_number = data.get("order_submission_number", "")
                order_duplicate_flag = data.get("order_duplicate_flag", False)
                order_submission_note = data.get("order_submission_note", "")

                counts["All"] += 1
                if case_status in counts:
                    counts[case_status] += 1

                if selected_status and case_status != selected_status:
                    continue

                haystack = " ".join([
                    case_id,
                    horse_name,
                    owner_name,
                    trainer_name,
                    discipline,
                    primary_question,
                    case_status,
                    case_priority,
                    shopify_order_number,
                    str(order_submission_number),
                    order_submission_note,
                ]).lower()

                if search_query and search_query not in haystack:
                    continue

                rows.append({
                    "case_id": case_id,
                    "horse_name": horse_name,
                    "owner_name": owner_name,
                    "discipline": discipline,
                    "status": case_status,
                    "priority": case_priority,
                    "primary_question": primary_question,
                    "submitted_at": data.get("submitted_at", ""),
                    "shopify_order_number": shopify_order_number,
                    "order_submission_number": order_submission_number,
                    "order_duplicate_flag": order_duplicate_flag,
                    "order_submission_note": order_submission_note,
                })

    return render_template(
        "cases.html",
        cases=rows,
        selected_status=selected_status,
        counts=counts,
        search_query=search_query
    )


@app.route("/cases/<case_id>")
@app.route("/cases/<case_id>/")
@app.route("/case/<case_id>")
@admin_required
def case_detail(case_id):
    case_folder = os.path.join(CASE_DIR, case_id)
    case_json = os.path.join(case_folder, "case.json")

    if not os.path.exists(case_json):
        return "Case not found", 404

    with open(case_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    return render_template(
        "case_detail.html",
        case_id=case_id,
        case=data,
        data=data
    )


@app.route("/cases/<case_id>/uploads/<filename>")
@admin_required
def case_upload(case_id, filename):
    uploads_folder = os.path.join(CASE_DIR, case_id, "uploads")
    return send_from_directory(uploads_folder, filename)


@app.route("/reports/<filename>")
@admin_required
def report_file(filename):
    return send_from_directory(REPORT_DIR, filename, as_attachment=True)


@app.route("/cases/<case_id>/status", methods=["POST"])
@admin_required
def update_case_status(case_id):
    case_json = os.path.join(CASE_DIR, case_id, "case.json")

    if not os.path.exists(case_json):
        return "Case not found", 404

    with open(case_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["status"] = request.form.get("status", data.get("status", "New"))

    with open(case_json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return redirect(url_for("case_detail", case_id=case_id))


@app.route("/cases/<case_id>/priority", methods=["POST"])
@admin_required
def update_case_priority(case_id):
    case_json = os.path.join(CASE_DIR, case_id, "case.json")

    if not os.path.exists(case_json):
        return "Case not found", 404

    with open(case_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["priority"] = request.form.get("priority", data.get("priority", "Standard"))

    with open(case_json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return redirect(url_for("case_detail", case_id=case_id))


@app.route("/cases/<case_id>/delete", methods=["POST"])
@admin_required
def delete_case(case_id):
    case_folder = os.path.join(CASE_DIR, case_id)
    report_path = os.path.join(REPORT_DIR, f"{case_id}.txt")

    if os.path.exists(case_folder):
        shutil.rmtree(case_folder)

    if os.path.exists(report_path):
        os.remove(report_path)

    return redirect(url_for("cases"))


@app.route("/cases/<case_id>/download")
@admin_required
def download_case(case_id):
    case_folder = os.path.join(CASE_DIR, case_id)
    uploads_folder = os.path.join(case_folder, "uploads")
    case_json = os.path.join(case_folder, "case.json")
    report_path = os.path.join(REPORT_DIR, f"{case_id}.txt")

    if not os.path.exists(case_json):
        return "Case not found", 404

    memory_file = BytesIO()

    with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(case_json, arcname=f"{case_id}/case.json")

        if os.path.exists(report_path):
            zf.write(report_path, arcname=f"{case_id}/ETI_Case_Report.txt")

        if os.path.isdir(uploads_folder):
            for filename in os.listdir(uploads_folder):
                filepath = os.path.join(uploads_folder, filename)
                if os.path.isfile(filepath):
                    zf.write(filepath, arcname=f"{case_id}/media/{filename}")

    memory_file.seek(0)

    return send_file(
        memory_file,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"ETI_Case_{case_id}.zip"
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
