import os
import json
import traceback
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, Response, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import io
import csv

from .autograder_logic_v2 import (
    load_rubric_prompt_from_file,
    run_full_evaluation,
    generate_student_facing_feedback,
    generate_explanation_for_score,
    DEFAULT_INTERNAL_RUBRIC_KEYS,
    CATEGORY_TO_INTERNAL_KEY_MAP
)

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER_V2 = os.path.join(BASE_DIR, "uploads_v2")
SUBMISSIONS_FOLDER_V2 = os.path.join(BASE_DIR, "submissions_v2")
RUBRIC_PROMPTS_FOLDER = os.path.join(BASE_DIR, "rubric_prompts")

CURRENT_RUBRIC_FILENAME = "current_rubric_hybrid.txt" # Using the hybrid rubric
CURRENT_RUBRIC_FILEPATH = os.path.join(RUBRIC_PROMPTS_FOLDER, CURRENT_RUBRIC_FILENAME)

SNIPPETS_FILENAME = "feedback_snippets.json" # For storing snippets
SNIPPETS_FILEPATH = os.path.join(BASE_DIR, SNIPPETS_FILENAME)


NUM_KEY_IMAGES_FOR_HYBRID = 10

os.makedirs(UPLOAD_FOLDER_V2, exist_ok=True)
os.makedirs(SUBMISSIONS_FOLDER_V2, exist_ok=True)
os.makedirs(RUBRIC_PROMPTS_FOLDER, exist_ok=True)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password123")

# --- Authentication ---
def check_auth(username, password): return username == ADMIN_USERNAME and password == ADMIN_PASSWORD
def authenticate(): return Response('Login Required', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password): return authenticate()
        return f(*args, **kwargs)
    return decorated_function

# --- Snippet Helper Functions ---
def load_feedback_snippets():
    if not os.path.exists(SNIPPETS_FILEPATH): return []
    try:
        with open(SNIPPETS_FILEPATH, 'r', encoding='utf-8') as f: snippets = json.load(f)
        return snippets
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading snippets file {SNIPPETS_FILEPATH}: {e}"); return []

def save_feedback_snippets(snippets):
    try:
        with open(SNIPPETS_FILEPATH, 'w', encoding='utf-8') as f:
            json.dump(snippets, f, indent=2, ensure_ascii=False)
        print(f"Feedback snippets saved to {SNIPPETS_FILEPATH}"); return True
    except IOError as e: print(f"Error saving snippets file {SNIPPETS_FILEPATH}: {e}"); return False

def generate_snippet_id():
    return f"snippet_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"


# --- Submission Helper Functions ---
def save_submission_data_v2(student_name, student_pid, architect_name, evaluation_results, student_feedback_summary):
    ts = datetime.now()
    safe_pid = "".join(c if c.isalnum() else "_" for c in student_pid)
    filename = f"{safe_pid}_{ts.strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(SUBMISSIONS_FOLDER_V2, filename)
    data = {
        "student_name": student_name, "student_pid": student_pid, "architect_name": architect_name,
        "submission_timestamp": ts.isoformat(), "grade": evaluation_results['grade'],
        "score_percent": evaluation_results['final_percent'], "rubric_scores": evaluation_results['rubric_scores'],
        "detailed_ai_evaluation": evaluation_results['detailed_evaluation_text'],
        "student_feedback_summary": student_feedback_summary,
        "raw_gemini_response": evaluation_results.get('raw_gemini_response', ''),
        "evaluation_mode": "hybrid", "num_key_images_processed": evaluation_results.get('num_key_images_processed')
    }
    try:
        with open(filepath, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Saved (hybrid): {filepath}")
    except Exception as e: print(f"Error saving {filepath}: {e}")

def get_all_submissions_data_v2():
    subs = []
    if not os.path.exists(SUBMISSIONS_FOLDER_V2): return subs
    for fname in sorted(os.listdir(SUBMISSIONS_FOLDER_V2), reverse=True):
        if fname.endswith('.json'):
            fpath = os.path.join(SUBMISSIONS_FOLDER_V2, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f: subs.append(json.load(f))
            except Exception as e: print(f"Error loading {fpath}: {e}")
    return subs

# --- Student Facing Routes ---
@app.route("/", methods=["GET"])
def student_homepage():
    return send_from_directory(os.path.join(BASE_DIR, "templates"), "frontend_v2.html")

@app.route("/submit_assignment", methods=["POST"])
def submit_assignment_route():
    if 'file' not in request.files: return jsonify({"error": "No file part."}), 400
    file = request.files["file"]; name = request.form.get("name","N/A"); pid = request.form.get("pid","N/A"); arch = request.form.get("architect","N/A")
    if file.filename == '': return jsonify({"error": "No selected file."}), 400
    if not file.filename.lower().endswith(".pdf"): return jsonify({"error": "PDF only."}), 400
    fname = secure_filename(f"{pid}_{file.filename}"); path = os.path.join(UPLOAD_FOLDER_V2, fname)
    try:
        file.save(path)
        rubric_text = load_rubric_prompt_from_file(CURRENT_RUBRIC_FILEPATH)
        eval_res = run_full_evaluation(
            path, arch, rubric_text, DEFAULT_INTERNAL_RUBRIC_KEYS, CATEGORY_TO_INTERNAL_KEY_MAP, NUM_KEY_IMAGES_FOR_HYBRID)
        stud_feed = generate_student_facing_feedback(name, pid, arch, eval_res)
        save_submission_data_v2(name, pid, arch, eval_res, stud_feed)
        return jsonify({
            "student_name": name, "student_pid": pid, "architect_name": arch,
            "grade": eval_res['grade'], "score": eval_res['final_percent'],
            "rubric_scores": eval_res['rubric_scores'],
            "detailed_evaluation": eval_res['detailed_evaluation_text'], "feedback": stud_feed
        }), 200
    except Exception as e: print(f"Error processing: {e}"); traceback.print_exc(); return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(path):
            try: os.remove(path)
            except Exception as er: print(f"Error removing temp: {er}")

# --- Admin Routes ---
@app.route("/admin", methods=["GET"])
@login_required
def admin_dashboard_page():
    return send_from_directory(os.path.join(BASE_DIR, "templates"), "admin_v2.html")

@app.route("/admin/api/rubric", methods=["GET", "POST"])
@login_required
def manage_rubric_route():
    if request.method == "GET":
        try: return jsonify({"rubric_prompt": load_rubric_prompt_from_file(CURRENT_RUBRIC_FILEPATH)})
        except Exception as e: return jsonify({"error": str(e)}), 500
    data = request.get_json(); prompt = data.get("rubric_prompt")
    if prompt is None: return jsonify({"error": "No rubric_prompt."}), 400
    try:
        with open(CURRENT_RUBRIC_FILEPATH, 'w', encoding='utf-8') as f: f.write(prompt)
        return jsonify({"message": "Rubric updated."})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/admin/api/evaluate_sample", methods=["POST"])
@login_required
def evaluate_sample_route():
    if 'file' not in request.files: return jsonify({"error": "No file part."}), 400
    file = request.files["file"]; arch = request.form.get("architect_name", "Sample")
    if file.filename == '': return jsonify({"error": "No selected file."}), 400
    if not file.filename.lower().endswith(".pdf"): return jsonify({"error": "PDF only."}), 400
    fname = secure_filename(f"sample_hybrid_{file.filename}"); path = os.path.join(UPLOAD_FOLDER_V2, fname)
    try:
        file.save(path)
        rubric_text = load_rubric_prompt_from_file(CURRENT_RUBRIC_FILEPATH)
        eval_res = run_full_evaluation(
            path, arch, rubric_text, DEFAULT_INTERNAL_RUBRIC_KEYS, CATEGORY_TO_INTERNAL_KEY_MAP, NUM_KEY_IMAGES_FOR_HYBRID)
        return jsonify(eval_res)
    except Exception as e: print(f"Sample eval error: {e}"); traceback.print_exc(); return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(path):
            try: os.remove(path)
            except Exception as er: print(f"Error removing sample: {er}")

@app.route("/admin/api/explain_score", methods=["POST"])
@login_required
def explain_score_route():
    data = request.get_json();
    if not data: return jsonify({"error": "Invalid JSON."}), 400
    arch = data.get("architect_name"); crit = data.get("criterion_name"); score = data.get("score_given"); feed = data.get("feedback_text")
    if not all([arch, crit, score is not None, feed is not None]): return jsonify({"error": "Missing fields."}), 400
    try:
        rubric = load_rubric_prompt_from_file(CURRENT_RUBRIC_FILEPATH)
        expl = generate_explanation_for_score(arch, crit, score, feed, rubric)
        return jsonify({"explanation": expl})
    except Exception as e: print(f"Explain error: {e}"); traceback.print_exc(); return jsonify({"error": str(e)}), 500

@app.route("/admin/api/submissions", methods=["GET"])
@login_required
def get_admin_submissions_route():
    return jsonify(get_all_submissions_data_v2())

@app.route("/admin/api/batch_grade_start", methods=["POST"])
@login_required
def batch_grade_start_route():
    if 'files[]' not in request.files: return jsonify({"error": "No files[]."}), 400
    files = request.files.getlist("files[]")
    if not files or all(f.filename == '' for f in files): return jsonify({"error": "No files."}), 400
    arch_name = request.form.get("architect_name", "Batch Architect")
    summary = []; processed = 0; errors = 0
    try: rubric_text = load_rubric_prompt_from_file(CURRENT_RUBRIC_FILEPATH)
    except Exception as e: return jsonify({"error": f"Rubric load error: {e}"}), 500
    
    for file in files:
        if file and file.filename.lower().endswith(".pdf"):
            bname = os.path.splitext(file.filename)[0]; pid = bname.split('_')[0] if '_' in bname else bname; name = bname.replace('_',' ')
            fname = secure_filename(f"batch_{pid}_{file.filename}"); path = os.path.join(UPLOAD_FOLDER_V2, fname)
            try:
                file.save(path)
                print(f"Batch: Proc {file.filename}")
                eval_res = run_full_evaluation(path, arch_name, rubric_text, DEFAULT_INTERNAL_RUBRIC_KEYS, CATEGORY_TO_INTERNAL_KEY_MAP, NUM_KEY_IMAGES_FOR_HYBRID)
                stud_feed = generate_student_facing_feedback(name, pid, arch_name, eval_res)
                save_submission_data_v2(name, pid, arch_name, eval_res, stud_feed)
                summary.append({"filename": file.filename, "status": "success", "grade": eval_res['grade'], "score": eval_res['final_percent']})
                processed += 1
            except Exception as e: print(f"Batch err {file.filename}: {e}"); summary.append({"filename": file.filename, "status":"error", "message":str(e)}); errors +=1
            finally:
                if os.path.exists(path):
                    try: os.remove(path)
                    except Exception as er: print(f"Err removing batch tmp: {er}")
        else: summary.append({"filename": file.filename, "status":"skipped", "message":"Not PDF"})
    return jsonify({"message": f"Batch done. Processed: {processed}, Errors: {errors}", "summary": summary})

@app.route("/admin/api/export_submissions", methods=["GET"])
@login_required
def export_submissions_route():
    fmt = request.args.get("format", "json").lower()
    subs = get_all_submissions_data_v2()
    if not subs: return jsonify({"message": "No subs to export."}), 404
    if fmt == "json": return jsonify(subs)
    if fmt == "csv":
        fields = ["student_name","student_pid","architect_name","submission_timestamp","grade","score_percent"]
        for k in DEFAULT_INTERNAL_RUBRIC_KEYS:
            dname = k;
            for dn, ik in CATEGORY_TO_INTERNAL_KEY_MAP.items():
                if ik == k: dname = dn; break
            fields.append(f"Score: {dname}")
        fields.extend(["detailed_ai_evaluation_snippet","student_feedback_summary_snippet"])
        output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for s in subs:
            row = {k:s.get(k) for k in ["student_name","student_pid","architect_name","submission_timestamp","grade","score_percent"]}
            row["detailed_ai_evaluation_snippet"] = (s.get("detailed_ai_evaluation","")[:200]+"...") if s.get("detailed_ai_evaluation") else ""
            row["student_feedback_summary_snippet"] = (s.get("student_feedback_summary","")[:200]+"...") if s.get("student_feedback_summary") else ""
            rs = s.get("rubric_scores", {})
            for ik in DEFAULT_INTERNAL_RUBRIC_KEYS:
                dn_h = ik;
                for dn, intern_k in CATEGORY_TO_INTERNAL_KEY_MAP.items():
                    if intern_k == ik: dn_h = dn; break
                row[f"Score: {dn_h}"] = rs.get(ik, "N/A")
            writer.writerow(row)
        csv_data = output.getvalue(); output.close()
        return Response(csv_data, mimetype="text/csv", headers={"Content-disposition":"attachment; filename=submissions.csv"})
    return jsonify({"error": "Unsupported format."}), 400

# --- Feedback Snippets API Routes ---
@app.route("/admin/api/snippets", methods=["GET"])
@login_required
def get_snippets_route():
    snippets = load_feedback_snippets()
    return jsonify(snippets), 200

@app.route("/admin/api/snippets", methods=["POST"])
@login_required
def add_snippet_route():
    data = request.get_json()
    if not data or "name" not in data or "content" not in data:
        return jsonify({"error": "Missing 'name' or 'content' for snippet."}), 400
    snippet_name = data["name"].strip()
    snippet_content = data["content"].strip()
    if not snippet_name or not snippet_content:
        return jsonify({"error": "Snippet name and content cannot be empty."}), 400
    snippets = load_feedback_snippets()
    new_snippet = {
        "id": generate_snippet_id(), "name": snippet_name,
        "content": snippet_content, "created_at": datetime.now().isoformat()
    }
    snippets.append(new_snippet)
    if save_feedback_snippets(snippets):
        return jsonify({"message": "Snippet added.", "snippet": new_snippet}), 201
    return jsonify({"error": "Failed to save snippet."}), 500

@app.route("/admin/api/snippets/<string:snippet_id>", methods=["PUT"])
@login_required
def update_snippet_route(snippet_id):
    data = request.get_json()
    if not data: return jsonify({"error": "Invalid JSON."}), 400
    snippets = load_feedback_snippets(); updated_snippet = None
    for snippet in snippets:
        if snippet["id"] == snippet_id:
            if "name" in data: snippet["name"] = data["name"].strip()
            if "content" in data: snippet["content"] = data["content"].strip()
            snippet["updated_at"] = datetime.now().isoformat()
            updated_snippet = snippet; break
    if not updated_snippet: return jsonify({"error": "Snippet not found."}), 404
    if save_feedback_snippets(snippets):
        return jsonify({"message": "Snippet updated.", "snippet": updated_snippet})
    return jsonify({"error": "Failed to save updated snippet."}), 500

@app.route("/admin/api/snippets/<string:snippet_id>", methods=["DELETE"])
@login_required
def delete_snippet_route(snippet_id):
    snippets = load_feedback_snippets()
    original_len = len(snippets)
    snippets = [s for s in snippets if s["id"] != snippet_id]
    if len(snippets) == original_len: return jsonify({"error": "Snippet not found."}), 404
    if save_feedback_snippets(snippets): return jsonify({"message": "Snippet deleted."})
    return jsonify({"error": "Failed to save after deletion."}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5001, debug=True)