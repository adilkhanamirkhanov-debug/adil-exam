import os
import re
import json
import random
import string
import sqlite3
import time
from types import SimpleNamespace

import mammoth
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, Response, abort,
)
from openai import OpenAI
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me-in-production")

# On Netlify (serverless) /tmp is the only writable path.
# Locally, override with DB_PATH environment variable.
DB_PATH = os.environ.get("DB_PATH", "/tmp/platform.db")

EMAIL_VALIDATION_PATTERN = (
    r"^(?![.])(?!.*[.]{2})[A-Za-z0-9._%+-]+(?<![.])@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
)

MYP_SUBJECT_CRITERIA = {
    "Не указано": {
        "A": "Критерий A", "B": "Критерий B",
        "C": "Критерий C", "D": "Критерий D",
    },
    "Науки (Sciences)": {
        "A": "Знание и понимание",
        "B": "Исследование и проектирование",
        "C": "Обработка и оценка",
        "D": "Осмысление влияния науки",
    },
    "Математика (Mathematics)": {
        "A": "Знание и понимание",
        "B": "Исследование закономерностей",
        "C": "Коммуникация",
        "D": "Применение математики",
    },
    "Язык и литература": {
        "A": "Анализ", "B": "Организация",
        "C": "Создание текста", "D": "Использование языка",
    },
    "Приобретение языка": {
        "A": "Аудирование", "B": "Чтение",
        "C": "Говорение", "D": "Письмо",
    },
    "Индивидуумы и общества": {
        "A": "Знание и понимание", "B": "Исследование",
        "C": "Коммуникация", "D": "Критическое мышление",
    },
    "Дизайн (Design)": {
        "A": "Исследование и анализ", "B": "Разработка идей",
        "C": "Создание решения", "D": "Оценка",
    },
    "Искусство (Arts)": {
        "A": "Знание и понимание", "B": "Развитие навыков",
        "C": "Творческое мышление", "D": "Отклик",
    },
    "Физкультура и здоровье (PHE)": {
        "A": "Знание и понимание",
        "B": "Планирование для достижения результата",
        "C": "Применение и выполнение",
        "D": "Рефлексия и улучшение",
    },
}

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
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
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            title TEXT,
            essay TEXT,
            grade TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS student_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            exam_title TEXT NOT NULL,
            question TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migrations: add columns if missing
    c.execute("PRAGMA table_info(exams_v3)")
    exam_cols = {row[1] for row in c.fetchall()}
    if "teacher_id" not in exam_cols:
        c.execute("ALTER TABLE exams_v3 ADD COLUMN teacher_id INTEGER")
    c.execute("PRAGMA table_info(teachers)")
    teacher_cols = {row[1] for row in c.fetchall()}
    if "is_admin" not in teacher_cols:
        c.execute("ALTER TABLE teachers ADD COLUMN is_admin INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_random_code(prefix="EXAM"):
    chars = string.ascii_uppercase + string.digits
    return f"{prefix}-" + "".join(random.choices(chars, k=5))


def build_in_clause(values):
    safe_values = [str(v) for v in values if v is not None]
    if not safe_values:
        return "", []
    placeholders = ",".join(["?"] * len(safe_values))
    if not re.fullmatch(r"^\?(,\?)*$", placeholders):
        raise ValueError("Unsafe SQL placeholders generated.")
    return placeholders, safe_values


def read_uploaded_file(file_storage):
    if file_storage and file_storage.filename:
        try:
            if file_storage.filename.endswith(".docx"):
                result = mammoth.convert_to_html(file_storage)
                return result.value
            else:
                return file_storage.read().decode("utf-8")
        except Exception:
            return ""
    return ""


# ── Auth helpers ──────────────────────────────────────────────────────────────

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

    is_admin_code = os.environ.get("ADMIN_REGISTRATION_CODE", "ADILEDU-ADMIN-2024")
    is_admin = 1 if admin_code.strip() == is_admin_code else 0

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO teachers (username, password_hash, email, is_admin) VALUES (?,?,?,?)",
            (username.strip(), generate_password_hash(password_clean), email_clean, is_admin),
        )
        conn.commit()
        role_msg = " (Администратор)" if is_admin else ""
        return True, f"Регистрация успешна{role_msg}! Теперь вы можете войти."
    except sqlite3.IntegrityError:
        return False, "Пользователь с таким username/email уже существует."
    finally:
        conn.close()


def authenticate_teacher(login_input, password):
    login_value = login_input.strip()
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id, username, password_hash, is_admin FROM teachers "
            "WHERE username=? OR lower(email)=?",
            (login_value, login_value.lower()),
        )
        teacher = c.fetchone()
        if teacher and check_password_hash(teacher[2], password.strip()):
            return teacher
        return None
    finally:
        conn.close()


# ── Teacher / exam DB helpers ─────────────────────────────────────────────────

def save_teacher_exam(code, exam_type, title, desc, criteria, strictness, time_limit, teacher_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT teacher_id FROM exams_v3 WHERE code=?", (code,))
        existing = c.fetchone()
        if existing and existing[0] is None:
            return False, "Этот код уже занят унаследованной задачей. Используйте новый код."
        if existing and existing[0] != teacher_id:
            return False, "Этот код уже занят другим учителем. Сгенерируйте новый."
        if existing:
            c.execute(
                "UPDATE exams_v3 SET type=?, title=?, desc=?, criteria=?, strictness=?, "
                "time_limit=?, teacher_id=? WHERE code=?",
                (exam_type, title, desc, criteria, strictness, time_limit, teacher_id, code),
            )
        else:
            c.execute(
                "INSERT INTO exams_v3 (code, type, title, desc, criteria, strictness, "
                "time_limit, teacher_id) VALUES (?,?,?,?,?,?,?,?)",
                (code, exam_type, title, desc, criteria, strictness, time_limit, teacher_id),
            )
        conn.commit()
        return True, "ok"
    finally:
        conn.close()


def get_teacher_exams(teacher_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT code, title, type, time_limit FROM exams_v3 "
            "WHERE teacher_id=? ORDER BY rowid DESC",
            (teacher_id,),
        )
        return c.fetchall()
    finally:
        conn.close()


def get_teacher_stats(teacher_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT type, COUNT(*) FROM exams_v3 WHERE teacher_id=? GROUP BY type",
            (teacher_id,),
        )
        type_counts = {row[0]: row[1] for row in c.fetchall()}
        c.execute("SELECT title FROM exams_v3 WHERE teacher_id=?", (teacher_id,))
        titles = [row[0] for row in c.fetchall()]
        if not titles:
            return type_counts, 0
        placeholders, safe_titles = build_in_clause(titles)
        c.execute(
            f"SELECT COUNT(*) FROM submissions WHERE title IN ({placeholders})",
            safe_titles,
        )
        row = c.fetchone()
        return type_counts, (row[0] if row else 0)
    finally:
        conn.close()


# ── AI helpers ────────────────────────────────────────────────────────────────

def get_ai_client():
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("API_KEY", "").strip(),
    )


def grade_essay(title, desc, criteria, strictness, essay, exam_type):
    if exam_type == "MYP":
        try:
            desc_data = json.loads(desc)
            if isinstance(desc_data, dict):
                parts = []
                if desc_data.get("conditions"):
                    parts.append(f"Условие: {desc_data['conditions']}")
                if desc_data.get("tasks"):
                    tasks_text = "\n".join(
                        f"{i+1}. {t['text']}" for i, t in enumerate(desc_data["tasks"])
                    )
                    parts.append(f"Задания:\n{tasks_text}")
                if desc_data.get("teacher_notes"):
                    parts.append(f"Замечания учителя: {desc_data['teacher_notes']}")
                if parts:
                    desc = "\n\n".join(parts)
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            crit_data = json.loads(criteria)
            if isinstance(crit_data, dict):
                lines = [
                    f"Предмет: {crit_data.get('subject', '')}",
                    f"Максимальный балл: {crit_data.get('max_score', '')}",
                ]
                for letter in crit_data.get("selected", []):
                    crit_name = crit_data.get("criteria_names", {}).get(letter, f"Критерий {letter}")
                    success = crit_data.get("success", {}).get(letter, "")
                    lines.append(f"\nКритерий {letter}: {crit_name}")
                    if success:
                        lines.append(f"Критерии успеха:\n{success}")
                criteria = "\n".join(lines)
        except (json.JSONDecodeError, TypeError):
            pass

    if strictness > 7:
        strictness_guide = (
            "Grade VERY strictly. Deduct points for any minor logical, "
            "grammatical, or structural mistakes. Be a tough grader."
        )
    elif strictness < 4:
        strictness_guide = (
            "Grade leniently and encouragingly. Focus on the main ideas "
            "and forgive minor mistakes."
        )
    else:
        strictness_guide = "Be balanced and fair."

    if exam_type == "MYP":
        system_instruction = (
            "ABSOLUTE RULE: This is an IB MYP Assessment. "
            "1. YOU MUST USE THE 1-8 SCALE for criteria and 1-7 SCALE for the final grade. "
            "2. DO NOT USE THE NUMBER 100. DO NOT write 'out of 100'. PERCENTAGES ARE BANNED."
        )
        format_instruction = (
            "Format:\n"
            "### Итоговая оценка MYP: [Итоговый балл 1-7]\n"
            "### Баллы по критериям: [Критерий A: x/8, ...]\n"
            "### Отзыв: [Детальный анализ по критериям MYP]"
        )
    else:
        system_instruction = (
            "CRITICAL INSTRUCTION 1: Evaluate the response on a standard 100-point scale "
            "based on the provided criteria."
        )
        format_instruction = (
            "Format:\n"
            "### Оценка: [X]/100\n"
            "### Отзыв: [Детальный анализ ответа]"
        )

    prompt = (
        f"Grade this response for the exam: '{title}'.\n"
        f"Task/Context: {desc}\n"
        f"Grading Criteria and Context: {criteria}\n"
        f"Strictness Level (1-10): {strictness}. {strictness_guide}\n\n"
        f"{system_instruction}\n\n"
        "CRITICAL INSTRUCTION 2: You MUST write your 'Feedback' in the EXACT SAME LANGUAGE "
        "that the student used in their 'Student's Work'.\n\n"
        f"Student's Work:\n{essay}\n\n"
        f"{format_instruction}"
    )
    client = get_ai_client()
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return response.choices[0].message.content


def generate_criteria_with_ai(title, desc, exam_type, subject=""):
    if exam_type == "MYP":
        type_instruction = (
            f"Use the official IB MYP rubric format (Criteria A/B/C/D, "
            f"bands 1-2, 3-4, 5-6, 7-8). Subject area: {subject}."
        )
    elif exam_type == "Quick":
        type_instruction = "Use a simple 100-point rubric with 3-4 clear criteria."
    else:
        type_instruction = "Create a detailed rubric with 4-5 criteria, each scored on a 0-10 scale."

    prompt = (
        "You are an expert educator. Generate clear, specific assessment criteria/success "
        "criteria for the following exam task.\n\n"
        f"Task Title: {title}\n"
        f"Task Description: {desc}\n"
        f"Exam Type: {exam_type}\n"
        f"{type_instruction}\n\n"
        "Requirements:\n"
        "- Write criteria in the SAME LANGUAGE as the task description\n"
        "- Be specific and measurable\n"
        "- Include what a top-scoring answer must demonstrate\n"
        "- Format as a clean rubric table or bullet list\n\n"
        "Generate the criteria now:"
    )
    client = get_ai_client()
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )
    return response.choices[0].message.content


def improve_criteria_with_ai(existing_criteria, exam_type):
    prompt = (
        f"You are an expert educator. Improve and refine the following assessment criteria "
        f"to make them clearer, more specific, and better aligned with best practices for "
        f"{exam_type} assessment.\n\n"
        f"Existing Criteria:\n{existing_criteria}\n\n"
        "Improvements to make:\n"
        "- Make language more precise and measurable\n"
        "- Add specific descriptors for each performance level\n"
        "- Remove vague or redundant language\n"
        "- Ensure criteria are student-friendly and understandable\n"
        "- Keep the SAME LANGUAGE as the original criteria\n\n"
        "Return only the improved criteria:"
    )
    client = get_ai_client()
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return response.choices[0].message.content


# ── Auth decorators ───────────────────────────────────────────────────────────

def require_teacher(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") not in ("Teacher", "Admin"):
            flash("Войдите в аккаунт учителя.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated


def require_admin(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "Admin":
            flash("Требуются права администратора.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated


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
        session["role"] = "Admin" if teacher[3] == 1 else "Teacher"
        session["teacher_id"] = teacher[0]
        session["teacher_username"] = teacher[1]
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
    flash(message, "success" if success else "error")
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/start-exam", methods=["POST"])
def start_exam():
    code = request.form.get("access_code", "").strip()
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT time_limit FROM exams_v3 WHERE code=?",
            (code,),
        )
        row = c.fetchone()
    finally:
        conn.close()

    if not row:
        flash("Код не найден или введён неверно.", "error")
        return redirect(url_for("index"))

    session["exam_code"] = code
    session["exam_start"] = time.time()
    session["exam_time_limit"] = row[0] or 0
    session.pop("already_submitted", None)
    session.pop("student_result", None)
    return redirect(url_for("exam", code=code))


@app.route("/exam/<code>")
def exam(code):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT code, type, title, desc, criteria, strictness, time_limit "
            "FROM exams_v3 WHERE code=?",
            (code,),
        )
        row = c.fetchone()
    finally:
        conn.close()

    if not row:
        abort(404)

    exam_obj = SimpleNamespace(
        code=row[0],
        type=row[1],
        title=row[2],
        desc=row[3],
        criteria=row[4],
        strictness=row[5],
        time_limit=row[6],
    )

    # Render MYP desc/criteria as HTML for display
    if exam_obj.type == "MYP":
        try:
            desc_data = json.loads(exam_obj.desc)
            if isinstance(desc_data, dict):
                parts = []
                if desc_data.get("conditions"):
                    parts.append(desc_data["conditions"])
                if desc_data.get("tasks"):
                    items = "".join(
                        f"<li>{t['text']}</li>" for t in desc_data["tasks"]
                    )
                    parts.append(f"<ol>{items}</ol>")
                if desc_data.get("teacher_notes"):
                    parts.append(f"<em>📌 {desc_data['teacher_notes']}</em>")
                exam_obj.desc = "<br>".join(parts) or exam_obj.desc
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            crit_data = json.loads(exam_obj.criteria)
            if isinstance(crit_data, dict):
                lines = [
                    f"<b>Предмет:</b> {crit_data.get('subject', '')}",
                    f"<b>Макс. балл:</b> {crit_data.get('max_score', '')}",
                    "<hr>",
                ]
                for letter in crit_data.get("selected", []):
                    name = crit_data.get("criteria_names", {}).get(letter, "")
                    success = crit_data.get("success", {}).get(letter, "")
                    lines.append(f"<b>Критерий {letter}: {name}</b>")
                    if success:
                        lines.append(success.replace("\n", "<br>"))
                    lines.append("<hr>")
                exam_obj.criteria = "<br>".join(lines)
        except (json.JSONDecodeError, TypeError):
            pass

    # Compute JS timer end time (milliseconds)
    end_time_ms = None
    if session.get("exam_code") == code:
        start_ts = session.get("exam_start")
        time_limit = session.get("exam_time_limit", 0)
        if start_ts and time_limit and time_limit > 0:
            end_time_ms = int((start_ts + time_limit * 60) * 1000)

    already_submitted = (
        session.get("already_submitted") and session.get("exam_code") == code
    )
    result = session.get("student_result") if already_submitted else None

    return render_template(
        "exam.html",
        exam=exam_obj,
        end_time_ms=end_time_ms,
        already_submitted=already_submitted,
        result=result,
    )


@app.route("/exam/<code>/submit", methods=["POST"])
def exam_submit(code):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT type, title, desc, criteria, strictness FROM exams_v3 WHERE code=?",
            (code,),
        )
        row = c.fetchone()
    finally:
        conn.close()

    if not row:
        abort(404)

    student_name = request.form.get("student_name", "").strip()
    essay = request.form.get("essay", "").strip()

    if not student_name or not essay:
        flash("Пожалуйста, заполните имя и напишите ответ.", "warning")
        return redirect(url_for("exam", code=code))

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM submissions WHERE name=? AND title=?",
            (student_name, row[1]),
        )
        if c.fetchone():
            flash(f"Ученик '{student_name}' уже сдавал этот экзамен.", "error")
            return redirect(url_for("exam", code=code))

        try:
            grade = grade_essay(row[1], row[2], row[3], row[4], essay, row[0])
            c.execute(
                "INSERT INTO submissions (name, title, essay, grade) VALUES (?,?,?,?)",
                (student_name, row[1], essay, grade),
            )
            conn.commit()
        except Exception:
            flash("⚠️ Операция не прошла. Попробуйте ещё раз.", "error")
            return redirect(url_for("exam", code=code))
    finally:
        conn.close()

    session["already_submitted"] = True
    session["student_result"] = grade
    session["exam_code"] = code
    return redirect(url_for("exam", code=code))


# ── Teacher routes ────────────────────────────────────────────────────────────

@app.route("/teacher/dashboard")
@require_teacher
def teacher_dashboard():
    teacher_id = session["teacher_id"]
    stats, total_submissions = get_teacher_stats(teacher_id)
    exams = get_teacher_exams(teacher_id)
    return render_template(
        "teacher_dashboard.html",
        stats=stats,
        total_submissions=total_submissions,
        exams=exams,
    )


@app.route("/teacher/create", methods=["GET", "POST"])
@require_teacher
def teacher_create():
    if request.method == "POST":
        teacher_id = session["teacher_id"]
        task_type = request.form.get("task_type", "Quick")
        code = request.form.get("code", "").strip()
        title = request.form.get("title", "").strip()
        criteria = request.form.get("criteria", "").strip()
        time_limit = int(request.form.get("time_limit", 45) or 0)
        strictness = float(request.form.get("strictness", 5) or 5)
        myp_subject = request.form.get("myp_subject", "Не указано")

        if not title:
            flash("Укажите название задачи.", "warning")
            return render_template("teacher_create.html")
        if not code:
            flash("Укажите код доступа.", "warning")
            return render_template("teacher_create.html")

        if task_type == "MYP":
            task_file = request.files.get("task_file")
            task_questions = request.form.get("task_questions", "")
            crit_file = request.files.get("crit_file")

            conditions = read_uploaded_file(task_file)
            if not conditions:
                conditions = task_questions.strip()

            tasks = [
                {"text": q.strip()}
                for q in task_questions.splitlines()
                if q.strip()
            ]

            desc = json.dumps(
                {"conditions": conditions, "tasks": tasks, "teacher_notes": ""},
                ensure_ascii=False,
            )

            crit_raw = read_uploaded_file(crit_file) if crit_file else ""
            subject_criteria = MYP_SUBJECT_CRITERIA.get(
                myp_subject, MYP_SUBJECT_CRITERIA["Не указано"]
            )
            selected = [ltr for ltr in ["A", "B", "C", "D"] if request.form.get(f"crit_{ltr}")]
            if not selected:
                selected = list(subject_criteria.keys())
            crit_json = json.dumps(
                {
                    "subject": myp_subject,
                    "selected": selected,
                    "criteria_names": {k: subject_criteria[k] for k in selected},
                    "success": {
                        k: request.form.get(f"success_{k}", "") for k in selected
                    },
                    "max_score": len(selected) * 8,
                },
                ensure_ascii=False,
            )
            final_crit = crit_raw or criteria or crit_json
        else:
            desc_text = request.form.get("desc", "").strip()
            desc_file = request.files.get("desc_file")
            file_content = read_uploaded_file(desc_file)
            desc_parts = [p for p in [desc_text, file_content] if p]
            desc = "<br>".join(desc_parts) or "Описание не указано."
            final_crit = criteria or "Оценить по содержательности, структуре и аргументации."

        saved, msg = save_teacher_exam(
            code, task_type, title, desc, final_crit,
            strictness, time_limit, teacher_id,
        )
        if saved:
            flash(f"✅ Задача опубликована! Код доступа: {code}", "success")
            return redirect(url_for("teacher_dashboard"))
        flash(msg, "error")
        return render_template("teacher_create.html")

    return render_template("teacher_create.html")


@app.route("/teacher/results")
@require_teacher
def teacher_results():
    teacher_id = session["teacher_id"]
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT title FROM exams_v3 WHERE teacher_id=?", (teacher_id,))
        titles = [row[0] for row in c.fetchall()]
        if not titles:
            return render_template("teacher_results.html", data=[])
        placeholders, safe_titles = build_in_clause(titles)
        c.execute(
            f"SELECT name, title, essay, grade FROM submissions "
            f"WHERE title IN ({placeholders})",
            safe_titles,
        )
        data = c.fetchall()
    finally:
        conn.close()
    return render_template("teacher_results.html", data=data)


@app.route("/teacher/results/download")
@require_teacher
def teacher_results_download():
    teacher_id = session["teacher_id"]
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT title FROM exams_v3 WHERE teacher_id=?", (teacher_id,))
        titles = [row[0] for row in c.fetchall()]
        if not titles:
            flash("Нет данных для скачивания.", "info")
            return redirect(url_for("teacher_results"))
        placeholders, safe_titles = build_in_clause(titles)
        c.execute(
            f"SELECT name, title, essay, grade FROM submissions "
            f"WHERE title IN ({placeholders})",
            safe_titles,
        )
        rows = c.fetchall()
    finally:
        conn.close()

    def esc(val):
        return '"' + str(val or "").replace('"', '""') + '"'

    lines = ["Имя,Экзамен,Эссе,Оценка"]
    for row in rows:
        lines.append(",".join(esc(v) for v in row))
    csv_data = "\n".join(lines)
    return Response(
        "\ufeff" + csv_data,
        mimetype="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=results.csv"},
    )


# ── Teacher JSON API endpoints ────────────────────────────────────────────────

@app.route("/teacher/generate-code", methods=["POST"])
@require_teacher
def teacher_generate_code():
    data = request.get_json(force=True, silent=True) or {}
    prefix = data.get("prefix", "EXAM")
    prefix = re.sub(r"[^A-Z0-9]", "", prefix.upper())[:8] or "EXAM"
    return jsonify({"code": generate_random_code(prefix)})


@app.route("/teacher/ai-criteria", methods=["POST"])
@require_teacher
def teacher_ai_criteria():
    data = request.get_json(force=True, silent=True) or {}
    title = data.get("title", "")
    desc = data.get("desc", "")
    exam_type = data.get("exam_type", "Quick")
    subject = data.get("subject", "")
    try:
        criteria = generate_criteria_with_ai(title, desc, exam_type, subject)
        return jsonify({"criteria": criteria})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/teacher/ai-improve", methods=["POST"])
@require_teacher
def teacher_ai_improve():
    data = request.get_json(force=True, silent=True) or {}
    existing = data.get("criteria", "")
    exam_type = data.get("exam_type", "Quick")
    if not existing:
        return jsonify({"error": "No criteria provided"}), 400
    try:
        improved = improve_criteria_with_ai(existing, exam_type)
        return jsonify({"criteria": improved})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Admin routes ──────────────────────────────────────────────────────────────

@app.route("/admin/teachers")
@require_admin
def admin_teachers():
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT id, username, email, is_admin, created_at FROM teachers ORDER BY id")
        teachers = [dict(row) for row in c.fetchall()]
    finally:
        conn.close()
    return render_template("admin_teachers.html", teachers=teachers)


@app.route("/admin/tasks")
@require_admin
def admin_tasks():
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT e.code, e.title, e.type, e.time_limit, t.username
            FROM exams_v3 e
            LEFT JOIN teachers t ON e.teacher_id = t.id
            ORDER BY e.rowid DESC
        """)
        exams = [dict(row) for row in c.fetchall()]
    finally:
        conn.close()
    return render_template("admin_tasks.html", exams=exams)


@app.route("/admin/results")
@require_admin
def admin_results():
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT id, name, title, essay, grade FROM submissions ORDER BY id DESC")
        rows = c.fetchall()
    finally:
        conn.close()

    if request.args.get("download") == "1":
        def esc(val):
            return '"' + str(val or "").replace('"', '""') + '"'

        lines = ["ID,Имя,Экзамен,Эссе,Оценка AI"]
        for row in rows:
            lines.append(",".join(esc(v) for v in row))
        csv_data = "\n".join(lines)
        return Response(
            "\ufeff" + csv_data,
            mimetype="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": "attachment; filename=all_results.csv"},
        )

    subs = [dict(row) for row in rows]
    return render_template("admin_results.html", subs=subs)


@app.route("/admin/delete-teacher", methods=["POST"])
@require_admin
def admin_delete_teacher():
    teacher_id = request.form.get("teacher_id", type=int)
    if not teacher_id:
        flash("Укажите ID учителя.", "error")
        return redirect(url_for("admin_teachers"))
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT username, is_admin FROM teachers WHERE id=?", (teacher_id,))
        target = c.fetchone()
        if not target:
            flash("Учитель с таким ID не найден.", "error")
        elif target[1] == 1:
            flash("Нельзя удалить администратора.", "error")
        else:
            c.execute("DELETE FROM teachers WHERE id=?", (teacher_id,))
            conn.commit()
            flash(f"Учитель «{target[0]}» удалён.", "success")
    finally:
        conn.close()
    return redirect(url_for("admin_teachers"))


@app.route("/admin/delete-task", methods=["POST"])
@require_admin
def admin_delete_task():
    code = request.form.get("code", "").strip()
    if not code:
        flash("Укажите код задачи.", "error")
        return redirect(url_for("admin_tasks"))
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT title FROM exams_v3 WHERE code=?", (code,))
        target = c.fetchone()
        if target:
            c.execute("DELETE FROM exams_v3 WHERE code=?", (code,))
            conn.commit()
            flash(f"Задача «{target[0]}» удалена.", "success")
        else:
            flash("Задача с таким кодом не найдена.", "error")
    finally:
        conn.close()
    return redirect(url_for("admin_tasks"))


@app.route("/admin/delete-submission", methods=["POST"])
@require_admin
def admin_delete_submission():
    sub_id = request.form.get("sub_id", type=int)
    if not sub_id:
        flash("Не указан ID записи.", "error")
        return redirect(url_for("admin_results"))
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM submissions WHERE id=?", (sub_id,))
        conn.commit()
        flash(f"Запись #{sub_id} удалена.", "success")
    finally:
        conn.close()
    return redirect(url_for("admin_results"))


# ── Bootstrap ─────────────────────────────────────────────────────────────────

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
