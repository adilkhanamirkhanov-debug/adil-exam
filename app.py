import os
import re
import random
import string
import sqlite3
import io
import time as _time
import logging

import pandas as pd
import mammoth
from openai import OpenAI
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_file, g
)
from dotenv import load_dotenv
from functools import wraps

logging.basicConfig(level=logging.INFO)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

EMAIL_VALIDATION_PATTERN = r"^(?![.])(?!.*[.]{2})[A-Za-z0-9._%+-]+(?<![.])@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"

DATABASE = "platform.db"


# ── Database ─────────────────────────────────────────────────────────────────

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE, check_same_thread=False)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS exams_v3 (
            code TEXT PRIMARY KEY,
            type TEXT,
            title TEXT,
            desc TEXT,
            criteria TEXT,
            strictness REAL,
            time_limit INTEGER,
            teacher_id INTEGER
        )
    ''')
    c.execute(
        'CREATE TABLE IF NOT EXISTS submissions '
        '(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, title TEXT, essay TEXT, grade TEXT)'
    )
    c.execute('''
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute("PRAGMA table_info(exams_v3)")
    exam_columns = [row[1] for row in c.fetchall()]
    if "teacher_id" not in exam_columns:
        c.execute("ALTER TABLE exams_v3 ADD COLUMN teacher_id INTEGER")
    c.execute("PRAGMA table_info(teachers)")
    teacher_columns = [row[1] for row in c.fetchall()]
    if "is_admin" not in teacher_columns:
        c.execute("ALTER TABLE teachers ADD COLUMN is_admin INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


init_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

def build_in_clause(values):
    """Build parameter placeholders and normalized values for SQL IN clauses."""
    safe_values = [str(v) for v in values if v is not None]
    if not safe_values:
        return "", []
    placeholders = ",".join(["?"] * len(safe_values))
    if not re.fullmatch(r"^\?(,\?)*$", placeholders):
        raise ValueError("Unsafe SQL placeholders generated.")
    return placeholders, safe_values


def generate_random_code(prefix="EXAM"):
    chars = string.ascii_uppercase + string.digits
    return f"{prefix}-" + "".join(random.choices(chars, k=5))


def read_uploaded_file(file_storage):
    if file_storage and file_storage.filename:
        try:
            if file_storage.filename.endswith(".docx"):
                result = mammoth.convert_to_html(file_storage)
                return result.value
            else:
                return file_storage.read().decode("utf-8")
        except Exception:
            return "Ошибка чтения файла."
    return ""


# ── Auth decorators ───────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") not in ("Teacher", "Admin"):
            flash("Войдите в систему, чтобы продолжить.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "Admin":
            flash("Доступ только для администраторов.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


# ── DB query helpers ──────────────────────────────────────────────────────────

def authenticate_teacher(login_input, password):
    login_value = login_input.strip()
    db = get_db()
    row = db.execute(
        "SELECT id, username, password_hash, is_admin FROM teachers "
        "WHERE username=? OR lower(email)=?",
        (login_value, login_value.lower())
    ).fetchone()
    if row and check_password_hash(row["password_hash"], password.strip()):
        return row
    return None


def register_teacher(username, email, password, admin_code=""):
    password_clean = password.strip()
    email_clean = email.strip()
    email_for_match = email_clean.lower()

    if len(username.strip()) < 3:
        return False, "Имя пользователя должно содержать минимум 3 символа."
    if len(password_clean) < 6:
        return False, "Пароль должен содержать минимум 6 символов."
    if not re.fullmatch(EMAIL_VALIDATION_PATTERN, email_for_match):
        return False, "Введите корректный email."

    admin_reg_code = os.environ.get("ADMIN_REGISTRATION_CODE", "ADILEDU-ADMIN-2024")
    is_admin = 1 if admin_code.strip() == admin_reg_code else 0

    try:
        db = get_db()
        db.execute(
            "INSERT INTO teachers (username, password_hash, email, is_admin) VALUES (?,?,?,?)",
            (username.strip(), generate_password_hash(password_clean), email_clean, is_admin)
        )
        db.commit()
        role_msg = " (Администратор)" if is_admin else ""
        return True, f"Регистрация успешна{role_msg}! Теперь вы можете войти."
    except sqlite3.IntegrityError:
        return False, "Пользователь с таким username/email уже существует."


def save_teacher_exam(code, exam_type, title, desc, criteria, strictness, time_limit, teacher_id):
    db = get_db()
    existing = db.execute("SELECT teacher_id FROM exams_v3 WHERE code=?", (code,)).fetchone()
    if existing and existing["teacher_id"] is None:
        return False, "Этот код уже занят унаследованной задачей. Используйте новый код."
    if existing and existing["teacher_id"] != teacher_id:
        return False, "Этот код уже занят другим учителем. Сгенерируйте новый."

    if existing:
        db.execute(
            "UPDATE exams_v3 SET type=?, title=?, desc=?, criteria=?, strictness=?, time_limit=?, teacher_id=? WHERE code=?",
            (exam_type, title, desc, criteria, strictness, time_limit, teacher_id, code)
        )
    else:
        db.execute(
            "INSERT INTO exams_v3 (code, type, title, desc, criteria, strictness, time_limit, teacher_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (code, exam_type, title, desc, criteria, strictness, time_limit, teacher_id)
        )
    db.commit()
    return True, "ok"


def get_teacher_exams(teacher_id):
    db = get_db()
    return db.execute(
        "SELECT code, title, type, time_limit FROM exams_v3 WHERE teacher_id=? ORDER BY rowid DESC",
        (teacher_id,)
    ).fetchall()


def get_teacher_stats(teacher_id):
    db = get_db()
    rows = db.execute(
        "SELECT type, COUNT(*) FROM exams_v3 WHERE teacher_id=? GROUP BY type", (teacher_id,)
    ).fetchall()
    type_counts = {row[0]: row[1] for row in rows}
    titles = [row["title"] for row in db.execute(
        "SELECT title FROM exams_v3 WHERE teacher_id=?", (teacher_id,)
    ).fetchall()]
    if not titles:
        return type_counts, 0
    placeholders, safe_titles = build_in_clause(titles)
    count = db.execute(
        f"SELECT COUNT(*) FROM submissions WHERE title IN ({placeholders})", safe_titles
    ).fetchone()[0]
    return type_counts, count


# ── AI ────────────────────────────────────────────────────────────────────────

def get_ai_client():
    api_key = os.environ.get("API_KEY", "").strip()
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)


def grade_essay(title, desc, criteria, strictness, essay, exam_type):
    strictness = float(strictness)
    if strictness > 7:
        strictness_guide = "Grade VERY strictly. Deduct points for any minor logical, grammatical, or structural mistakes. Be a tough grader."
    elif strictness < 4:
        strictness_guide = "Grade leniently and encouragingly. Focus on the main ideas and forgive minor mistakes."
    else:
        strictness_guide = "Be balanced and fair."

    if exam_type == "MYP":
        system_instruction = (
            "ABSOLUTE RULE: This is an IB MYP Assessment. "
            "1. YOU MUST USE THE 1-8 SCALE for criteria and 1-7 SCALE for the final grade. "
            "2. DO NOT USE THE NUMBER 100. DO NOT write \"out of 100\". PERCENTAGES ARE BANNED."
        )
        format_instruction = (
            "Format:\n"
            "### Итоговая оценка MYP: [Итоговый балл 1-7]\n"
            "### Баллы по критериям: [Критерий A: x/8, Критерий B: x/8...]\n"
            "### Отзыв: [Детальный анализ по критериям MYP]"
        )
    else:
        system_instruction = "CRITICAL INSTRUCTION 1: Evaluate the response on a standard 100-point scale based on the provided criteria."
        format_instruction = (
            "Format:\n"
            "### Оценка: [X]/100\n"
            "### Отзыв: [Детальный анализ ответа]"
        )

    prompt = f"""Grade this response for the exam: '{title}'.
Task/Context: {desc}
Grading Criteria and Context: {criteria}
Strictness Level (1-10): {strictness}. {strictness_guide}

{system_instruction}

CRITICAL INSTRUCTION 2: You MUST write your 'Feedback' in the EXACT SAME LANGUAGE that the student used in their 'Student's Work'.

Student's Work:
{essay}

{format_instruction}
"""
    client = get_ai_client()
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return response.choices[0].message.content


def generate_criteria_with_ai(title, desc, exam_type, subject="", difficulty="Medium"):
    if exam_type == "MYP":
        type_instruction = f"Use the official IB MYP rubric format (Criteria A/B/C/D, bands 1-2, 3-4, 5-6, 7-8). Subject area: {subject}."
    elif exam_type == "Quick":
        type_instruction = "Use a simple 100-point rubric with 3-4 clear criteria."
    else:
        type_instruction = "Create a detailed rubric with 4-5 criteria, each scored on a 0-10 scale."

    prompt = f"""You are an expert educator. Generate clear, specific assessment criteria/success criteria for the following exam task.

Task Title: {title}
Task Description: {desc}
Exam Type: {exam_type}
Difficulty Level: {difficulty}
{type_instruction}

Requirements:
- Write criteria in the SAME LANGUAGE as the task description
- Be specific and measurable
- Include what a top-scoring answer must demonstrate
- Format as a clean rubric table or bullet list

Generate the criteria now:"""

    client = get_ai_client()
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4
    )
    return response.choices[0].message.content


def improve_criteria_with_ai(existing_criteria, exam_type):
    prompt = f"""You are an expert educator. Improve and refine the following assessment criteria to make them clearer, more specific, and better aligned with best practices for {exam_type} assessment.

Existing Criteria:
{existing_criteria}

Improvements to make:
- Make language more precise and measurable
- Add specific descriptors for each performance level
- Remove vague or redundant language
- Ensure criteria are student-friendly and understandable
- Keep the SAME LANGUAGE as the original criteria

Return only the improved criteria:"""

    client = get_ai_client()
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return response.choices[0].message.content


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    teacher = authenticate_teacher(username, password)
    if teacher:
        session["teacher_id"] = teacher["id"]
        session["teacher_username"] = teacher["username"]
        session["role"] = "Admin" if teacher["is_admin"] == 1 else "Teacher"
        if session["role"] == "Admin":
            return redirect(url_for("admin_teachers"))
        return redirect(url_for("teacher_dashboard"))
    flash("Неверный логин или пароль.", "error")
    return redirect(url_for("index"))


@app.route("/register", methods=["POST"])
def register():
    username = request.form.get("reg_username", "")
    email = request.form.get("reg_email", "")
    password = request.form.get("reg_password", "")
    admin_code = request.form.get("admin_code", "")
    success, message = register_teacher(username, email, password, admin_code)
    if success:
        flash(message, "success")
    else:
        flash(message, "error")
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ── Teacher routes ────────────────────────────────────────────────────────────

@app.route("/teacher")
@login_required
def teacher_dashboard():
    teacher_id = session["teacher_id"]
    stats, total_submissions = get_teacher_stats(teacher_id)
    exams = get_teacher_exams(teacher_id)
    return render_template(
        "teacher_dashboard.html",
        stats=stats,
        total_submissions=total_submissions,
        exams=exams
    )


@app.route("/teacher/create", methods=["GET", "POST"])
@login_required
def teacher_create():
    if request.method == "POST":
        teacher_id = session["teacher_id"]
        task_variant = request.form.get("task_type", "Quick")
        code = request.form.get("code", "").strip()
        title = request.form.get("title", "").strip()
        criteria_manual = request.form.get("criteria", "").strip()
        strictness = float(request.form.get("strictness", 5))
        time_limit = int(request.form.get("time_limit", 45))
        myp_subject = request.form.get("myp_subject", "Не указано")
        task_questions = request.form.get("task_questions", "")

        if not title:
            flash("Укажите название задачи.", "error")
            return redirect(url_for("teacher_create"))
        if not code:
            flash("Укажите код доступа.", "error")
            return redirect(url_for("teacher_create"))

        if task_variant == "MYP":
            task_file = request.files.get("task_file")
            crit_file = request.files.get("crit_file")
            desc_content = read_uploaded_file(task_file)
            questions_html = (
                f"<br><h3>Вопросы:</h3><p>{task_questions.replace(chr(10), '<br>')}</p>"
                if task_questions.strip() else ""
            )
            final_desc = (desc_content + questions_html) or "Смотрите вопросы."
            subject_prefix = (
                f"[ПРЕДМЕТ MYP: {myp_subject}]\n\n"
                if "Не указано" not in myp_subject else ""
            )
            final_crit = subject_prefix + (criteria_manual or read_uploaded_file(crit_file)) or "Оценивать по стандартам MYP."
        else:
            c_desc = request.form.get("desc", "").strip()
            c_file = request.files.get("desc_file")
            file_desc = read_uploaded_file(c_file)
            desc_parts = [p.strip() for p in [c_desc, file_desc] if p.strip()]
            final_desc = "<br>".join(desc_parts) or "Описание не указано."
            final_crit = criteria_manual or "Оценить по содержательности, структуре и аргументации."

        saved, save_message = save_teacher_exam(
            code, task_variant, title, final_desc, final_crit,
            strictness, time_limit, teacher_id
        )
        if saved:
            flash(f"✅ Задача опубликована! Код доступа: {code}", "success")
            return redirect(url_for("teacher_dashboard"))
        else:
            flash(save_message, "error")
            return redirect(url_for("teacher_create"))

    return render_template("teacher_create.html")


@app.route("/teacher/generate-code", methods=["POST"])
@login_required
def teacher_generate_code():
    prefix = request.json.get("prefix", "EXAM")
    return jsonify({"code": generate_random_code(prefix)})


@app.route("/teacher/ai-criteria", methods=["POST"])
@login_required
def teacher_ai_criteria():
    data = request.json
    try:
        result = generate_criteria_with_ai(
            data.get("title", ""),
            data.get("desc", ""),
            data.get("exam_type", "Quick"),
            subject=data.get("subject", ""),
            difficulty=data.get("difficulty", "Medium")
        )
        return jsonify({"criteria": result})
    except Exception as exc:
        logging.exception("AI criteria generation failed: %s", exc)
        return jsonify({"error": "AI service error. Please try again."}), 500


@app.route("/teacher/ai-improve", methods=["POST"])
@login_required
def teacher_ai_improve():
    data = request.json
    existing = data.get("criteria", "").strip()
    if not existing:
        return jsonify({"error": "Нет критериев для улучшения"}), 400
    try:
        result = improve_criteria_with_ai(existing, data.get("exam_type", "Quick"))
        return jsonify({"criteria": result})
    except Exception as exc:
        logging.exception("AI criteria improvement failed: %s", exc)
        return jsonify({"error": "AI service error. Please try again."}), 500


@app.route("/teacher/results")
@login_required
def teacher_results():
    teacher_id = session["teacher_id"]
    db = get_db()
    teacher_titles = [
        row["title"] for row in db.execute(
            "SELECT title FROM exams_v3 WHERE teacher_id=?", (teacher_id,)
        ).fetchall()
    ]
    data = []
    if teacher_titles:
        placeholders, safe_titles = build_in_clause(teacher_titles)
        data = db.execute(
            f"SELECT name, title, essay, grade FROM submissions WHERE title IN ({placeholders})",
            safe_titles
        ).fetchall()
    return render_template("teacher_results.html", data=data)


@app.route("/teacher/results/download")
@login_required
def teacher_results_download():
    teacher_id = session["teacher_id"]
    db = get_db()
    teacher_titles = [
        row["title"] for row in db.execute(
            "SELECT title FROM exams_v3 WHERE teacher_id=?", (teacher_id,)
        ).fetchall()
    ]
    data = []
    if teacher_titles:
        placeholders, safe_titles = build_in_clause(teacher_titles)
        data = db.execute(
            f"SELECT name, title, essay, grade FROM submissions WHERE title IN ({placeholders})",
            safe_titles
        ).fetchall()
    df = pd.DataFrame(data, columns=["Имя", "Экзамен", "Эссе", "Оценка"])
    buf = io.BytesIO()
    buf.write(df.to_csv(index=False).encode("utf-8-sig"))
    buf.seek(0)
    return send_file(buf, mimetype="text/csv", as_attachment=True, download_name="results.csv")


# ── Admin routes ──────────────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin_teachers():
    db = get_db()
    teachers = db.execute(
        "SELECT id, username, email, is_admin, created_at FROM teachers ORDER BY id"
    ).fetchall()
    return render_template("admin_teachers.html", teachers=teachers)


@app.route("/admin/delete-teacher", methods=["POST"])
@admin_required
def admin_delete_teacher():
    teacher_id = request.form.get("teacher_id", type=int)
    db = get_db()
    target = db.execute(
        "SELECT username, is_admin FROM teachers WHERE id=?", (teacher_id,)
    ).fetchone()
    if target is None:
        flash("Учитель с таким ID не найден.", "error")
    elif target["is_admin"] == 1:
        flash("Нельзя удалить администратора.", "error")
    else:
        db.execute("DELETE FROM teachers WHERE id=?", (teacher_id,))
        db.commit()
        flash(f"Учитель «{target['username']}» удалён.", "success")
    return redirect(url_for("admin_teachers"))


@app.route("/admin/tasks")
@admin_required
def admin_tasks():
    db = get_db()
    exams = db.execute(
        "SELECT e.code, e.title, e.type, e.time_limit, t.username "
        "FROM exams_v3 e LEFT JOIN teachers t ON e.teacher_id = t.id "
        "ORDER BY e.rowid DESC"
    ).fetchall()
    return render_template("admin_tasks.html", exams=exams)


@app.route("/admin/delete-task", methods=["POST"])
@admin_required
def admin_delete_task():
    code = request.form.get("code", "").strip()
    db = get_db()
    target = db.execute("SELECT title FROM exams_v3 WHERE code=?", (code,)).fetchone()
    if target:
        db.execute("DELETE FROM exams_v3 WHERE code=?", (code,))
        db.commit()
        flash(f"Задача «{target['title']}» удалена.", "success")
    else:
        flash("Задача с таким кодом не найдена.", "error")
    return redirect(url_for("admin_tasks"))


@app.route("/admin/results")
@admin_required
def admin_results():
    db = get_db()
    subs = db.execute(
        "SELECT id, name, title, essay, grade FROM submissions ORDER BY id DESC"
    ).fetchall()
    return render_template("admin_results.html", subs=subs)


@app.route("/admin/delete-submission", methods=["POST"])
@admin_required
def admin_delete_submission():
    sub_id = request.form.get("sub_id", type=int)
    db = get_db()
    db.execute("DELETE FROM submissions WHERE id=?", (sub_id,))
    db.commit()
    flash(f"Запись #{sub_id} удалена.", "success")
    return redirect(url_for("admin_results"))


# ── Exam / Student routes ─────────────────────────────────────────────────────

@app.route("/start-exam", methods=["POST"])
def start_exam():
    code = request.form.get("access_code", "").strip()
    if not code:
        flash("Введите код доступа.", "error")
        return redirect(url_for("index"))
    db = get_db()
    exam = db.execute(
        "SELECT code, type, title, desc, criteria, strictness, time_limit "
        "FROM exams_v3 WHERE code=?", (code,)
    ).fetchone()
    if exam:
        return redirect(url_for("exam_page", code=exam["code"]))
    flash("Код не найден или введён неверно.", "error")
    return redirect(url_for("index"))


@app.route("/exam/<code>")
def exam_page(code):
    db = get_db()
    exam = db.execute(
        "SELECT code, type, title, desc, criteria, strictness, time_limit "
        "FROM exams_v3 WHERE code=?", (code,)
    ).fetchone()
    if not exam:
        flash("Экзамен не найден.", "error")
        return redirect(url_for("index"))

    end_time_ms = None
    if exam["time_limit"] and exam["time_limit"] > 0:
        # Persist end time in session so page refreshes don't reset the timer
        timer_key = f"exam_end_time_{code}"
        if timer_key not in session:
            session[timer_key] = int((_time.time() + exam["time_limit"] * 60) * 1000)
        end_time_ms = session[timer_key]

    result = session.pop("exam_result", None)
    already_submitted = session.pop("exam_submitted", False)

    return render_template(
        "exam.html",
        exam=dict(exam),
        end_time_ms=end_time_ms,
        result=result,
        already_submitted=already_submitted
    )


@app.route("/exam/<code>/submit", methods=["POST"])
def exam_submit(code):
    db = get_db()
    exam = db.execute(
        "SELECT code, type, title, desc, criteria, strictness, time_limit "
        "FROM exams_v3 WHERE code=?", (code,)
    ).fetchone()
    if not exam:
        flash("Экзамен не найден.", "error")
        return redirect(url_for("index"))

    s_name = request.form.get("student_name", "").strip()
    s_essay = request.form.get("essay", "").strip()

    if not s_name or not s_essay:
        flash("Пожалуйста, заполните имя и напишите ответ.", "error")
        return redirect(url_for("exam_page", code=code))

    # Server-side time limit enforcement
    if exam["time_limit"] and exam["time_limit"] > 0:
        timer_key = f"exam_end_time_{code}"
        end_time_ms = session.get(timer_key)
        if end_time_ms and int(_time.time() * 1000) > end_time_ms:
            flash("Время на выполнение экзамена истекло. Работа не принята.", "error")
            return redirect(url_for("exam_page", code=code))

    existing = db.execute(
        "SELECT id FROM submissions WHERE name=? AND title=?",
        (s_name, exam["title"])
    ).fetchone()
    if existing:
        flash(f"Ученик '{s_name}' уже сдавал этот экзамен.", "error")
        return redirect(url_for("exam_page", code=code))

    try:
        grade = grade_essay(
            exam["title"], exam["desc"], exam["criteria"],
            exam["strictness"], s_essay, exam["type"]
        )
    except Exception as e:
        grade = f"Ошибка AI оценивания: {e}"

    db.execute(
        "INSERT INTO submissions (name, title, essay, grade) VALUES (?,?,?,?)",
        (s_name, exam["title"], s_essay, grade)
    )
    db.commit()

    session["exam_result"] = grade
    session["exam_submitted"] = True
    # Clear the timer for this exam from session
    session.pop(f"exam_end_time_{code}", None)
    return redirect(url_for("exam_page", code=code))


if __name__ == "__main__":
    app.run(debug=False)
