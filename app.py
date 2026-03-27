from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import json
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CASE_DIR = os.path.join(BASE_DIR, "data", "cases")
REPORT_DIR = os.path.join(BASE_DIR, "data", "reports")
CONFIG_DIR = os.path.join(BASE_DIR, "config")

os.makedirs(CASE_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 500

def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def make_case_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8]

def save_uploads(files, folder: str):
    saved = []
    os.makedirs(folder, exist_ok=True)
    for f in files:
        if not f or not getattr(f, "filename", ""):
            continue
        filename = secure_filename(f.filename)
        path = os.path.join(folder, filename)
        f.save(path)
        saved.append(filename)
    return saved

def compute_scores(form: dict, scoring_template: dict) -> dict:
    symptoms = set(form.get("symptoms", []))
    question = (form.get("primary_question") or "").lower()
    story = (form.get("horse_story") or "").lower()

    scores = {"hydration": 2, "gut": 2, "muscle": 2, "metabolic": 2}

    if "Slow recovery" in symptoms or "Flat performance" in symptoms:
        scores["hydration"] += 2
        scores["muscle"] += 2
    if "Digestive instability" in symptoms:
        scores["gut"] += 3
    if "Random/phantom lameness" in symptoms or "Stopping at fences" in symptoms:
        scores["muscle"] += 2
        scores["metabolic"] += 1
    if "Tight or anxious" in symptoms:
        scores["metabolic"] += 3
        scores["hydration"] += 1

    if "ulcer" in question or "gut" in question or "manure" in story:
        scores["gut"] += 2
    if "tight" in question or "hot" in story or "anxious" in question:
        scores["metabolic"] += 2
    if "fatigue" in question or "fade" in story or "not finishing" in question:
        scores["hydration"] += 2
        scores["muscle"] += 1

    result = {}
    for pillar, raw in scores.items():
        raw = min(raw, 10)
        band = "Stable"
        for span, label in scoring_template[pillar]["bands"].items():
            start, end = [int(x) for x in span.split("-")]
            if start <= raw <= end:
                band = label
                break
        result[pillar] = {"score": raw, "band": band}
    return result

LOCKED_SECTIONS = [
    "Horse Identification and Presenting Concern",
    "Intake Summary",
    "Eye Image Review",
    "Movement / Video Review",
    "Terrain Interpretation",
    "Progression Pattern",
    "What This Looks Like If Ignored",
    "ETI Conclusion",
    "Tom to Trainer",
    "Next-Step Framework",
]

def build_locked_sections(form: dict) -> dict:
    horse = form.get("horse_name") or "This horse"
    discipline = form.get("discipline") or "general performance"
    question = form.get("primary_question") or "No primary question entered."
    story = form.get("horse_story") or "No horse story entered."
    symptoms = ", ".join(form.get("symptoms", [])) or "No symptom boxes selected."
    eye_count = len(form.get("files", {}).get("eye_photos", []))
    body_count = len(form.get("files", {}).get("body_photos", []))
    video_count = len(form.get("files", {}).get("videos", []))
    scores = form["scores"]

    return {
        "Horse Identification and Presenting Concern":
            f"{horse} was submitted as a {discipline} case. The primary question entered was: {question} This report preserves the locked ETI order and frames the horse as a whole-system terrain case, not a loose collection of symptoms.",
        "Intake Summary":
            f"Reported symptoms include: {symptoms} The intake history reads as follows: {story} Feed, supplementation, water behavior, travel, surface, and turnout details should be treated as biologic inputs that shape the horse’s terrain.",
        "Eye Image Review":
            f"{eye_count} eye image file(s) were submitted. This section remains fixed in place for ETI eye language, pattern references, and image quality qualifiers.",
        "Movement / Video Review":
            f"{body_count} body photo file(s) and {video_count} video file(s) were submitted. This section is reserved for stride pattern, symmetry, compensation, and improve → plateau → regress commentary where supported.",
        "Terrain Interpretation":
            f"This horse is not presenting with a random problem. This is a pattern. Current score summary indicates hydration {scores['hydration']['score']}/10 ({scores['hydration']['band']}), gut {scores['gut']['score']}/10 ({scores['gut']['band']}), muscle {scores['muscle']['score']}/10 ({scores['muscle']['band']}), and metabolic {scores['metabolic']['score']}/10 ({scores['metabolic']['band']}). This section should remain explanatory, physiologic, and confident in tone.",
        "Progression Pattern":
            "The purpose of this section is to state whether the horse appears to be improving, plateauing, or regressing, and where compensation may already be masking the true case.",
        "What This Looks Like If Ignored":
            "If this terrain pattern continues without correction, the likely direction is greater inconsistency, reduced confidence, more obvious compensation, and eventual breakdown in performance quality.",
        "ETI Conclusion":
            "The ETI conclusion should synthesize the full case and state clearly what is most likely driving the present pattern, without sounding vague or padded.",
        "Tom to Trainer":
            "If this were mine, I would want this section to feel direct, plainspoken, and practical. It should sound like Tom speaking to the trainer about what matters right now.",
        "Next-Step Framework":
            "This section should preserve the same ETI order every time: immediate priorities, monitoring priorities, and follow-up review needs. It should not be condensed.",
    }

def write_report(case_id: str, form: dict) -> str:
    report_path = os.path.join(REPORT_DIR, f"{case_id}.txt")
    lines = [
        "Equine Terrain Institute",
        "The New Science of the Modern Horse: The Terrain Revolution",
        "",
        f"Case ID: {case_id}",
        f"Horse: {form.get('horse_name', '')}",
        f"Discipline: {form.get('discipline', '')}",
        "",
        "Scores:",
    ]
    for pillar in ["hydration", "gut", "muscle", "metabolic"]:
        s = form["scores"][pillar]
        lines.append(f"- {pillar.title()}: {s['score']} ({s['band']})")
    lines.append("")
    for section in LOCKED_SECTIONS:
        lines.append(section)
        lines.append(form["locked_sections"][section])
        lines.append("")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path

@app.route("/", methods=["GET", "POST"])
def intake():
    if request.method == "POST":
        case_id = make_case_id()
        case_folder = os.path.join(CASE_DIR, case_id)
        uploads_folder = os.path.join(case_folder, "uploads")
        os.makedirs(case_folder, exist_ok=True)

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
        }

        form["files"] = {
            "eye_photos": save_uploads(request.files.getlist("eye_photos"), os.path.join(uploads_folder, "eye_photos")),
            "body_photos": save_uploads(request.files.getlist("body_photos"), os.path.join(uploads_folder, "body_photos")),
            "videos": save_uploads(request.files.getlist("videos"), os.path.join(uploads_folder, "videos")),
        }

        scoring_template = load_json(os.path.join(CONFIG_DIR, "scoring_template.json"))
        form["scores"] = compute_scores(form, scoring_template)
        form["locked_sections"] = build_locked_sections(form)
        form["status"] = "New"

        with open(os.path.join(case_folder, "case.json"), "w", encoding="utf-8") as f:
            json.dump(form, f, indent=2)

        write_report(case_id, form)
        return redirect(url_for("success"))

    return render_template("index.html")
@app.route("/cases")
def cases():
    selected_status = request.args.get("status", "").strip()

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

                counts["All"] += 1
                if case_status in counts:
                    counts[case_status] += 1

                if selected_status and case_status != selected_status:
                    continue

                rows.append({
                    "case_id": case_id,
                    "horse_name": data.get("horse_name", ""),
                    "discipline": data.get("discipline", ""),
                    "status": case_status,
                    "primary_question": data.get("primary_question", ""),
                    "submitted_at": data.get("submitted_at", ""),
                })

    return render_template(
        "cases.html",
        cases=rows,
        selected_status=selected_status,
        counts=counts
    ))

@app.route("/cases/<case_id>")
def case_detail(case_id):
    @app.route("/cases/<case_id>/status", methods=["POST"])
def update_case_status(case_id):
    case_json = os.path.join(CASE_DIR, case_id, "case.json")
    if not os.path.exists(case_json):
        return "Case not found", 404

    with open(case_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    new_status = request.form.get("status", "New")
    allowed_statuses = ["New", "In Review", "Report Drafted", "Complete"]

    if new_status not in allowed_statuses:
        new_status = "New"

    data["status"] = new_status

    with open(case_json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return redirect(url_for("case_detail", case_id=case_id))
    case_json = os.path.join(CASE_DIR, case_id, "case.json")
    if not os.path.exists(case_json):
        return "Case not found", 404
    with open(case_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    return render_template("case_detail.html", case_id=case_id, data=data)

@app.route("/reports/<filename>")
def reports(filename):
    return send_from_directory(REPORT_DIR, filename)

@app.route("/api/health")
def health():
    return jsonify({"ok": True, "service": "eti-clean-render-package"})
@app.route("/success")
def success():
    return render_template("success.html")
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
