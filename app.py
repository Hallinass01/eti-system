from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import json
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
CASE_DIR = os.path.join(BASE_DIR, "data", "cases")
REPORT_DIR = os.path.join(BASE_DIR, "data", "reports")
CONFIG_DIR = os.path.join(BASE_DIR, "config")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CASE_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 500


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def make_case_id():
    return datetime.utcnow().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8]


def save_files(files, folder):
    saved = []
    os.makedirs(folder, exist_ok=True)

    for f in files:
        if f and f.filename:
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
        "Tom to Trainer":
            "Direct practical notes go here.",
        "Next-Step Framework":
            "Immediate priorities, monitoring, follow-up."
    }


def write_report(case_id, form):
    report_path = os.path.join(REPORT_DIR, f"{case_id}.txt")

    lines = [
        "Equine Terrain Institute",
        "",
        f"Case ID: {case_id}",
        f"Horse: {form.get('horse_name','')}",
        ""
    ]

    for section, text in form["locked_sections"].items():
        lines.append(section)
        lines.append(text)
        lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


@app.route("/", methods=["GET", "POST"])
def intake():
    if request.method == "POST":
        case_id = make_case_id()
        case_folder = os.path.join(CASE_DIR, case_id)
        uploads_folder = os.path.join(case_folder, "uploads")

        os.makedirs(case_folder, exist_ok=True)
        os.makedirs(uploads_folder, exist_ok=True)

        eye_paths = save_files(request.files.getlist("eye_photos"), uploads_folder)
        body_paths = save_files(request.files.getlist("body_photos"), uploads_folder)
        video_paths = save_files(request.files.getlist("videos"), uploads_folder)

        form = {
            "submitted_at": datetime.utcnow().isoformat() + "Z",
            "horse_name": request.form.get("horse_name", ""),
            "owner_name": request.form.get("owner_name", ""),
            "trainer_name": request.form.get("trainer_name", ""),
            "discipline": request.form.get("discipline", ""),
            "breed": request.form.get("breed", ""),
            "age": request.form.get("age", ""),
            "sex": request.form.get("sex", ""),
            "location": request.form.get("location", ""),
            "primary_question": request.form.get("primary_question", ""),
            "horse_story": request.form.get("horse_story", ""),
            "feed_program": request.form.get("feed_program", ""),
            "supplement_program": request.form.get("supplement_program", ""),
            "water_notes": request.form.get("water_notes", ""),
            "travel_notes": request.form.get("travel_notes", ""),
            "surface_notes": request.form.get("surface_notes", ""),
            "turnout_notes": request.form.get("turnout_notes", ""),
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

        return redirect(url_for("case_detail", case_id=case_id))

    return render_template("index.html")


@app.route("/cases")
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
                with open(case_json, "r", encoding="utf-8") as f:
                    data = json.load(f)

                case_status = data.get("status", "New")
                case_priority = data.get("priority", "Standard")
                horse_name = data.get("horse_name", "")
                owner_name = data.get("owner_name", "")
                trainer_name = data.get("trainer_name", "")
                discipline = data.get("discipline", "")
                primary_question = data.get("primary_question", "")

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
                ]).lower()

                if search_query and search_query not in haystack:
                    continue

                rows.append({
                    "case_id": case_id,
                    "horse_name": horse_name,
                    "discipline": discipline,
                    "status": case_status,
                    "priority": case_priority,
                    "primary_question": primary_question,
                    "submitted_at": data.get("submitted_at", ""),
                })

    return render_template(
        "cases.html",
        cases=rows,
        selected_status=selected_status,
        counts=counts,
        search_query=search_query
    )


@app.route("/success")
def success():
    return render_template("success.html")


@app.route("/api/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
