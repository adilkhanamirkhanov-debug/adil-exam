import streamlit as st
import sqlite3
import pandas as pd
from openai import OpenAI
import random
import string
import time 
import re
import json
import imghdr
from datetime import datetime
import mammoth 
import streamlit.components.v1 as components
from werkzeug.security import generate_password_hash, check_password_hash

EMAIL_VALIDATION_PATTERN = r"^(?![.])(?!.*[.]{2})[A-Za-z0-9._%+-]+(?<![.])@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"

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
        "A": "Анализ",
        "B": "Организация",
        "C": "Создание текста",
        "D": "Использование языка",
    },
    "Приобретение языка": {
        "A": "Аудирование",
        "B": "Чтение",
        "C": "Говорение",
        "D": "Письмо",
    },
    "Индивидуумы и общества": {
        "A": "Знание и понимание",
        "B": "Исследование",
        "C": "Коммуникация",
        "D": "Критическое мышление",
    },
    "Дизайн (Design)": {
        "A": "Исследование и анализ",
        "B": "Разработка идей",
        "C": "Создание решения",
        "D": "Оценка",
    },
    "Искусство (Arts)": {
        "A": "Знание и понимание",
        "B": "Развитие навыков",
        "C": "Творческое мышление",
        "D": "Отклик",
    },
    "Физкультура и здоровье (PHE)": {
        "A": "Знание и понимание",
        "B": "Планирование для достижения результата",
        "C": "Применение и выполнение",
        "D": "Рефлексия и улучшение",
    },
}

PLATFORM_INSTRUCTION_MD = """
**🔐 Вход и регистрация**
- Зарегистрируйтесь, введя имя, email и пароль (мин. 6 символов).
- Войдите по username или email.
- Если у вас есть код администратора — введите его при регистрации.

---

**⚡ Создание задачи**

Нажмите **«Создать задачу»** в меню. Выберите тип:

- **Quick** — быстрое эссе / краткий ответ. Одна рубрика, простая настройка.
- **MYP** — официальный формат IB MYP с критериями A/B/C/D по предмету.
- **Custom** — полностью кастомная задача.

**Шаги конструктора:**
1. Введите код доступа (или нажмите 🎲 для автогенерации).
2. Укажите название задачи.
3. Напишите условие задачи (или загрузите файл .docx/.txt).
4. Добавьте критерии оценивания вручную или с помощью кнопок AI.
5. Для MYP: выберите предмет и критерии, добавьте критерии успеха.
6. Настройте время и строгость AI-оценивания.
7. Нажмите **«Опубликовать»**.

---

**🤖 AI-помощник**
- **Сгенерировать критерии** — AI создаёт рубрику по названию и условию задачи.
- **Улучшить критерии** — AI дорабатывает уже введённые критерии.
- **Шаблон рубрики** — вставляет готовый шаблон для выбранного типа задачи.
- **🤖 AI** (в MYP) — генерирует критерии успеха для конкретного критерия.

---

**📤 Раздача кода студентам**
- После публикации задачи скопируйте **код доступа**.
- Студент вводит код на главной странице платформы и начинает экзамен.

---

**📋 Результаты**
- В разделе **«Результаты»** отображаются все работы ваших студентов.
- Можно просмотреть ответ и AI-оценку каждого студента.
- Нажмите **«Скачать CSV»**, чтобы сохранить таблицу результатов.

---

**⏱ Таймер и прокторинг**
- Установите лимит времени (0 = без ограничений).
- Прокторинг автоматически фиксирует: переключение вкладок, выход из окна, копирование и вставку.

---

**❓ Если что-то пошло не так**
- При ошибке AI появится сообщение **«Операция не прошла»** — просто попробуйте ещё раз.
- Данные задач сохраняются в базе и не теряются при обновлении страницы.
"""

# --- 1. CONFIG ---
st.set_page_config(
    page_title="fair-exam", 
    layout="wide", 
    initial_sidebar_state="expanded" 
)

# --- 2. CSS LOADING ---
def load_css(file_name):
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except:
        pass

load_css("style.css")

# --- 3. SESSION STATE & URL RECOVERY ---
if "role" not in st.session_state: st.session_state.role = None
if "gen_code" not in st.session_state: st.session_state.gen_code = ""
if "exam_submitted" not in st.session_state: st.session_state.exam_submitted = False
if "student_grade" not in st.session_state: st.session_state.student_grade = ""
if "exam_end_time" not in st.session_state: st.session_state.exam_end_time = None
if "student_draft" not in st.session_state: st.session_state.student_draft = ""
if "teacher_id" not in st.session_state: st.session_state.teacher_id = None
if "teacher_username" not in st.session_state: st.session_state.teacher_username = None
if "task_step" not in st.session_state: st.session_state.task_step = 1
if "task_type_sel" not in st.session_state: st.session_state.task_type_sel = None
if "ai_criteria_result" not in st.session_state: st.session_state.ai_criteria_result = ""
if "myp_tasks" not in st.session_state: st.session_state.myp_tasks = [{"text": "", "active": True, "id": 0}]
if "myp_task_counter" not in st.session_state: st.session_state.myp_task_counter = 1
if "myp_success_criteria" not in st.session_state: st.session_state.myp_success_criteria = {}
if "wizard_criteria" not in st.session_state: st.session_state.wizard_criteria = ""
if "teacher_status_saved" not in st.session_state: st.session_state.teacher_status_saved = "Создаю сильные экзамены с AI 🚀"
if "teacher_bio_saved" not in st.session_state: st.session_state.teacher_bio_saved = "Преподаватель и наставник. Люблю понятные критерии и честную проверку."
if "teacher_avatar" not in st.session_state: st.session_state.teacher_avatar = None
if "profile_public_saved" not in st.session_state: st.session_state.profile_public_saved = True
if "profile_public" not in st.session_state: st.session_state.profile_public = st.session_state.profile_public_saved
if "teacher_workspace_mode" not in st.session_state: st.session_state.teacher_workspace_mode = "🎯 Focus mode"

def update_draft():
    # Функция сохраняет текст при каждом изменении (когда кликают вне поля)
    st.session_state.student_draft = st.session_state.essay_input

# ВОССТАНОВЛЕНИЕ СЕССИИ ИЗ URL (Если обновили страницу)
if st.session_state.role is None and "exam_code" in st.query_params:
    code_from_url = st.query_params["exam_code"]
    conn = sqlite3.connect('platform.db', check_same_thread=False)
    c = conn.cursor()
    # Проверяем, существует ли таблица exams_v3, чтобы избежать ошибок при первом запуске
    try:
        c.execute("SELECT type, title, desc, criteria, strictness, time_limit FROM exams_v3 WHERE code=?", (code_from_url,))
        res = c.fetchone()
        if res:
            st.session_state.current_exam = {
                "type": res[0], "title": res[1], "desc": res[2], 
                "criteria": res[3], "strictness": res[4], "time_limit": res[5]
            }
            st.session_state.role = "Student"
            # При жестком обновлении таймер начнется заново (т.к. старая память стерлась)
            if res[5] > 0 and st.session_state.exam_end_time is None:
                st.session_state.exam_end_time = time.time() + (res[5] * 60)
    except sqlite3.OperationalError:
        pass # Таблица еще не создана

if st.session_state.role != "Student":
    st.markdown("""<style>[data-testid="collapsedControl"] {display: flex !important; top: 25px !important;} section[data-testid="stSidebar"] {display: flex !important;}</style>""", unsafe_allow_html=True)
else:
    st.markdown("""<style>[data-testid="collapsedControl"], section[data-testid="stSidebar"] {display: none !important;}</style>""", unsafe_allow_html=True)

# --- 4. DATABASE ---
def init_db():
    conn = sqlite3.connect('platform.db', check_same_thread=False)
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
    c.execute('CREATE TABLE IF NOT EXISTS submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, title TEXT, essay TEXT, grade TEXT)')
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
    c.execute('''
        CREATE TABLE IF NOT EXISTS student_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            exam_title TEXT NOT NULL,
            question TEXT NOT NULL,
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
    return conn

db_conn = init_db()

def generate_random_code(prefix="EXAM"):
    chars = string.ascii_uppercase + string.digits
    return f"{prefix}-" + "".join(random.choices(chars, k=5))

def read_file(uploaded_file):
    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith('.docx'):
                result = mammoth.convert_to_html(uploaded_file)
                return result.value
            else:
                return uploaded_file.getvalue().decode("utf-8")
        except Exception as e:
            return "Ошибка чтения файла. Убедитесь, что это не поврежденный файл."
    return ""

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

    is_admin_code = st.secrets.get("ADMIN_REGISTRATION_CODE", "ADILEDU-ADMIN-2024")
    is_admin = 1 if admin_code.strip() == is_admin_code else 0

    try:
        c = db_conn.cursor()
        c.execute(
            "INSERT INTO teachers (username, password_hash, email, is_admin) VALUES (?,?,?,?)",
            (username.strip(), generate_password_hash(password_clean), email_clean, is_admin)
        )
        db_conn.commit()
        role_msg = " (Администратор)" if is_admin else ""
        return True, f"Регистрация успешна{role_msg}! Теперь вы можете войти."
    except sqlite3.IntegrityError:
        return False, "Пользователь с таким username/email уже существует."

def authenticate_teacher(login_input, password):
    login_value = login_input.strip()
    c = db_conn.cursor()
    c.execute(
        "SELECT id, username, password_hash, is_admin FROM teachers WHERE username=? OR lower(email)=?",
        (login_value, login_value.lower())
    )
    teacher = c.fetchone()
    if teacher and check_password_hash(teacher[2], password.strip()):
        return teacher
    return None

def save_teacher_exam(code, exam_type, title, desc, criteria, strictness, time_limit, teacher_id):
    c = db_conn.cursor()
    c.execute("SELECT teacher_id FROM exams_v3 WHERE code=?", (code,))
    existing = c.fetchone()
    if existing and existing[0] is None:
        return False, "Этот код уже занят унаследованной задачей. Используйте новый код."
    if existing and existing[0] != teacher_id:
        return False, "Этот код уже занят другим учителем. Сгенерируйте новый."

    if existing:
        c.execute(
            "UPDATE exams_v3 SET type=?, title=?, desc=?, criteria=?, strictness=?, time_limit=?, teacher_id=? WHERE code=?",
            (exam_type, title, desc, criteria, strictness, time_limit, teacher_id, code)
        )
    else:
        c.execute(
            "INSERT INTO exams_v3 (code, type, title, desc, criteria, strictness, time_limit, teacher_id) VALUES (?,?,?,?,?,?,?,?)",
            (code, exam_type, title, desc, criteria, strictness, time_limit, teacher_id)
        )
    db_conn.commit()
    return True, "ok"

def get_teacher_exams(teacher_id, exam_type=None):
    c = db_conn.cursor()
    if exam_type:
        c.execute(
            "SELECT code, title, type, time_limit FROM exams_v3 WHERE teacher_id=? AND type=? ORDER BY rowid DESC",
            (teacher_id, exam_type)
        )
    else:
        c.execute(
            "SELECT code, title, type, time_limit FROM exams_v3 WHERE teacher_id=? ORDER BY rowid DESC",
            (teacher_id,)
        )
    return c.fetchall()

def get_teacher_stats(teacher_id):
    c = db_conn.cursor()
    c.execute("SELECT type, COUNT(*) FROM exams_v3 WHERE teacher_id=? GROUP BY type", (teacher_id,))
    type_counts = {row[0]: row[1] for row in c.fetchall()}
    c.execute("SELECT title FROM exams_v3 WHERE teacher_id=?", (teacher_id,))
    titles = [row[0] for row in c.fetchall()]
    if not titles:
        return type_counts, 0
    placeholders, safe_titles = build_in_clause(titles)
    c.execute(f"SELECT COUNT(*) FROM submissions WHERE title IN ({placeholders})", safe_titles)
    submissions_count = c.fetchone()[0]
    return type_counts, submissions_count

def build_teacher_profile(stats, total_submissions):
    """Builds a simple progress profile from available totals (no timestamp data available)."""
    total_exams = int(sum(stats.values()))
    xp = total_exams * 12 + total_submissions * 7
    level = max(1, (xp // 100) + 1)
    current_level_base = (level - 1) * 100
    next_level_xp = level * 100
    level_span = next_level_xp - current_level_base
    level_progress = (xp - current_level_base) / level_span if level_span else 0.0
    level_progress = max(0.0, min(1.0, level_progress))
    return {
        "total_exams": total_exams,
        "xp": xp,
        "level": level,
        "next_level_xp": next_level_xp,
        "level_progress": level_progress,
        "activity_index": min(100, total_exams * 10 + total_submissions * 3),
        "impact_score": total_exams * 5 + total_submissions * 2,
    }

def get_teacher_achievements(stats, total_submissions, total_exams):
    return [
        ("🚀 Первый запуск", total_exams >= 1, "Создать первую задачу"),
        ("🎯 Конструктор мастер", total_exams >= 5, "Опубликовать 5 задач"),
        ("📨 Проверка потока", total_submissions >= 10, "Получить 10 отправленных работ"),
        ("🎓 MYP Pro", stats.get("MYP", 0) >= 3, "Сделать 3 MYP задачи"),
        ("⚡ Speed Creator", stats.get("Quick", 0) >= 3, "Сделать 3 Quick задачи"),
        ("🧠 Автор кастома", stats.get("Custom", 0) >= 2, "Сделать 2 Custom задачи"),
    ]

def build_in_clause(values):
    """Build parameter placeholders and normalized values for SQL IN clauses."""
    safe_values = [str(v) for v in values if v is not None]
    if not safe_values:
        return "", []
    placeholders = ",".join(["?"] * len(safe_values))
    if not re.fullmatch(r"^\?(,\?)*$", placeholders):
        raise ValueError("Unsafe SQL placeholders generated.")
    return placeholders, safe_values

# --- 5. AI LOGIC ---
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=st.secrets["API_KEY"].strip(),
)

def grade_essay(title, desc, criteria, strictness, essay, exam_type):
    # Parse JSON for structured MYP exams
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

    strictness_guide = "Be balanced and fair."
    if strictness > 7:
        strictness_guide = "Grade VERY strictly. Deduct points for any minor logical, grammatical, or structural mistakes. Be a tough grader."
    elif strictness < 4:
        strictness_guide = "Grade leniently and encouragingly. Focus on the main ideas and forgive minor mistakes."

    if exam_type == "MYP":
        system_instruction = """
        ABSOLUTE RULE: This is an IB MYP Assessment. 
        1. YOU MUST USE THE 1-8 SCALE for criteria and 1-7 SCALE for the final grade.
        2. DO NOT USE THE NUMBER 100. DO NOT write "out of 100". PERCENTAGES ARE BANNED.
        """
        format_instruction = """
        Format: 
        ### Итоговая оценка MYP: [Итоговый балл 1-7]
        ### Баллы по критериям: [Критерий A: x/8, Критерий B: x/8...]
        ### Отзыв: [Детальный анализ по критериям MYP]
        """
    else:
        system_instruction = "CRITICAL INSTRUCTION 1: Evaluate the response on a standard 100-point scale based on the provided criteria."
        format_instruction = """
        Format: 
        ### Оценка: [X]/100 
        ### Отзыв: [Детальный анализ ответа]
        """

    prompt = f"""
    Grade this response for the exam: '{title}'.
    Task/Context: {desc}
    Grading Criteria and Context: {criteria}
    Strictness Level (1-10): {strictness}. {strictness_guide}
    
    {system_instruction}
    
    CRITICAL INSTRUCTION 2: You MUST write your 'Feedback' in the EXACT SAME LANGUAGE that the student used in their 'Student's Work'.
    
    Student's Work: 
    {essay}
    
    {format_instruction}
    """
    
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return response.choices[0].message.content

def generate_criteria_with_ai(title, desc, exam_type, subject="", difficulty="Medium"):
    """Ask AI to generate assessment criteria/rubric for a given task."""
    type_instruction = ""
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

    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4
    )
    return response.choices[0].message.content

def improve_criteria_with_ai(existing_criteria, exam_type):
    """Ask AI to improve/refine existing criteria."""
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

    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return response.choices[0].message.content

# --- 6. NAVIGATION ---

# ГЛАВНЫЙ ЭКРАН (ВХОД)
if st.session_state.role is None:
    with st.sidebar:
        st.markdown("### 🔐 Teacher Space")
        login_tab, register_tab = st.tabs(["Вход", "Регистрация"])
        with login_tab:
            t_user = st.text_input("Username или Email")
            t_pass = st.text_input("Password", type="password")
            if st.button("Login", type="primary"):
                teacher = authenticate_teacher(t_user, t_pass)
                if teacher:
                    # teacher = (id, username, password_hash, is_admin)
                    if teacher[3] == 1:
                        st.session_state.role = "Admin"
                    else:
                        st.session_state.role = "Teacher"
                    st.session_state.teacher_id = teacher[0]
                    st.session_state.teacher_username = teacher[1]
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error("Неверный логин или пароль.")
        with register_tab:
            new_user = st.text_input("Новый username")
            new_email = st.text_input("Email")
            new_pass = st.text_input("Новый пароль", type="password")
            admin_code_input = st.text_input("Код администратора (необязательно)", type="password",
                                              help="Если вы получили специальный код — введите его. Это даст права администратора.")
            if admin_code_input:
                st.caption("⚠️ Правильный код даст вам права администратора платформы.")
            if st.button("Создать аккаунт", type="secondary"):
                success, message = register_teacher(new_user, new_email, new_pass, admin_code_input)
                if success:
                    st.success(message)
                else:
                    st.warning(message)

    st.markdown("<br><br><br>", unsafe_allow_html=True)

    # Animated brain network canvas
    components.html("""
<style>
  #brain-canvas { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; z-index: 0; pointer-events: none; }
</style>
<canvas id="brain-canvas"></canvas>
<script>
(function(){
  const canvas = document.getElementById('brain-canvas');
  const ctx = canvas.getContext('2d');
  let W = canvas.width = window.innerWidth;
  let H = canvas.height = window.innerHeight;
  window.addEventListener('resize', () => { W = canvas.width = window.innerWidth; H = canvas.height = window.innerHeight; });

  const NODE_COUNT = 55;
  const MAX_DIST = 160;
  const nodes = [];

  for (let i = 0; i < NODE_COUNT; i++) {
    nodes.push({
      x: Math.random() * W,
      y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.45,
      vy: (Math.random() - 0.5) * 0.45,
      r: Math.random() * 3 + 2,
      pulse: Math.random() * Math.PI * 2
    });
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    const t = Date.now() / 1000;

    // Draw edges
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const dist = Math.sqrt(dx*dx + dy*dy);
        if (dist < MAX_DIST) {
          const alpha = (1 - dist / MAX_DIST) * 0.35;
          const grad = ctx.createLinearGradient(nodes[i].x, nodes[i].y, nodes[j].x, nodes[j].y);
          grad.addColorStop(0, `rgba(161,140,209,${alpha})`);
          grad.addColorStop(1, `rgba(123,227,255,${alpha})`);
          ctx.beginPath();
          ctx.strokeStyle = grad;
          ctx.lineWidth = 1;
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.stroke();
        }
      }
    }

    // Draw nodes
    for (const n of nodes) {
      n.pulse += 0.025;
      const glow = 0.55 + 0.45 * Math.sin(n.pulse);
      const radius = n.r + 1.5 * Math.sin(n.pulse);

      const grad = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, radius * 3.5);
      grad.addColorStop(0, `rgba(251,194,235,${glow * 0.95})`);
      grad.addColorStop(0.5, `rgba(161,140,209,${glow * 0.5})`);
      grad.addColorStop(1, `rgba(161,140,209,0)`);
      ctx.beginPath();
      ctx.arc(n.x, n.y, radius * 3.5, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.beginPath();
      ctx.arc(n.x, n.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(251,194,235,${glow})`;
      ctx.fill();

      // Move
      n.x += n.vx;
      n.y += n.vy;
      if (n.x < 0 || n.x > W) n.vx *= -1;
      if (n.y < 0 || n.y > H) n.vy *= -1;
    }
    requestAnimationFrame(draw);
  }
  draw();
})();
</script>
""", height=0)

    st.markdown('<p class="logo-text">fair-exam</p>', unsafe_allow_html=True)
    st.markdown(
        """
        <div style="max-width: 980px; margin: 0 auto 24px auto; text-align: center; color: #e8d9ff;">
            <p style="font-size: 18px; margin-bottom: 4px;"><b>Интеллектуальная платформа для экзаменов и оценки ответов с AI</b></p>
            <p style="opacity: 0.85;">Учителя создают задачи в едином конструкторе, а ученики входят только по коду доступа.</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    left_card, right_card = st.columns(2)
    with left_card:
        st.markdown(
            """
                <div style="padding: 18px; border-radius: 14px; border: 1px solid rgba(255,255,255,0.15); background: rgba(255,255,255,0.04);">
                <h3 style="margin-top:0;">👨‍🎓 Student mode</h3>
                <ul>
                    <li>Введите код доступа</li>
                    <li>Отправьте ответ и получите AI-оценку</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True
        )
    with right_card:
        st.markdown(
            """
                <div style="padding: 18px; border-radius: 14px; border: 1px solid rgba(255,255,255,0.15); background: rgba(255,255,255,0.04);">
                <h3 style="margin-top:0;">👩‍🏫 Teacher mode</h3>
                <ul>
                    <li>Зарегистрируйтесь и войдите в кабинет</li>
                    <li>Создавайте задачи в едином техно-конструкторе</li>
                    <li>Отслеживайте статистику и результаты</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True
        )
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<p style='text-align: center; opacity: 0.7;'>Введите код доступа от учителя</p>", unsafe_allow_html=True)
        access_code = st.text_input("Код", placeholder="Например: MYP-1A2B3", label_visibility="collapsed")
        
        if st.button("Начать экзамен", type="primary"):
            c = db_conn.cursor()
            c.execute("SELECT type, title, desc, criteria, strictness, time_limit FROM exams_v3 WHERE code=?", (access_code,))
            res = c.fetchone()
            if res:
                st.session_state.current_exam = {
                    "type": res[0], "title": res[1], "desc": res[2], 
                    "criteria": res[3], "strictness": res[4], "time_limit": res[5]
                }
                st.session_state.role = "Student"
                st.session_state.exam_submitted = False
                st.session_state.student_grade = ""
                
                if res[5] > 0:
                    st.session_state.exam_end_time = time.time() + (res[5] * 60)
                else:
                    st.session_state.exam_end_time = None
                    
                # ЗАПИСЫВАЕМ КОД В URL, чтобы не выкинуло при обновлении
                st.query_params["exam_code"] = access_code
                st.rerun()
            else:
                st.error("Код не найден или введен неверно.")

# ПАНЕЛЬ УЧИТЕЛЯ (КАБИНЕТ)
elif st.session_state.role == "Teacher":
    if st.session_state.teacher_id is None:
        st.session_state.role = None
        st.warning("Сессия учителя не найдена. Пожалуйста, войдите снова.")
        st.rerun()

    teacher_id = st.session_state.teacher_id
    teacher_username = st.session_state.teacher_username

    with st.sidebar:
        st.markdown(f"""
        <div style="text-align:center; padding: 12px 0 8px 0;">
            <div style="font-size:36px;">🧑‍🏫</div>
            <div style="font-size:15px; color:#fbc2eb; font-weight:700;">{teacher_username}</div>
            <div style="font-size:11px; color:rgba(255,255,255,0.5);">Teacher Account</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("---")
        teacher_menu_options = ["🏠 Личный кабинет", "⚡ Создать задачу", "📋 Результаты"]
        if st.session_state.get("teacher_menu_selection") not in teacher_menu_options:
            st.session_state.teacher_menu_selection = teacher_menu_options[0]
        menu_selection = st.radio(
            "Навигация:",
            teacher_menu_options,
            key="teacher_menu_selection",
            label_visibility="collapsed"
        )
        st.markdown("---")
        if st.button("🚪 Выйти", type="primary"):
            st.session_state.role = None
            st.session_state.teacher_id = None
            st.session_state.teacher_username = None
            st.session_state.task_step = 1
            st.session_state.task_type_sel = None
            st.session_state.pop("teacher_menu_selection", None)
            st.query_params.clear()
            st.rerun()

    # Намеренно в основной области (не в sidebar), чтобы отображалось как отдельное окно.
    with st.expander("🪟 Инструкция по платформе", expanded=False):
        st.markdown(PLATFORM_INSTRUCTION_MD)

    if menu_selection == "🏠 Личный кабинет":
        st.header("🏠 Личный кабинет преподавателя")
        stats, total_submissions = get_teacher_stats(teacher_id)
        all_teacher_exams = get_teacher_exams(teacher_id)
        profile = build_teacher_profile(stats, total_submissions)
        achievements = get_teacher_achievements(stats, total_submissions, profile["total_exams"])

        left_col, right_col = st.columns([1.05, 1.95], gap="large")

        with left_col:
            st.markdown("### 👤 Профиль")
            avatar_file = st.file_uploader("Загрузить аватар", type=["png", "jpg", "jpeg"], key="teacher_avatar_upload")
            if avatar_file is not None:
                avatar_bytes = avatar_file.getvalue()
                detected_type = imghdr.what(None, avatar_bytes)
                if len(avatar_bytes) > 5 * 1024 * 1024:
                    st.warning("Размер аватарки должен быть не больше 5MB.")
                elif detected_type not in {"png", "jpeg"}:
                    st.warning("Загрузите изображение в формате PNG или JPG.")
                else:
                    st.session_state.teacher_avatar = avatar_bytes

            if st.session_state.teacher_avatar:
                st.image(st.session_state.teacher_avatar, width=140)
            else:
                st.markdown(
                    """<div class="avatar-placeholder">+</div><div class="avatar-hint">Место для аватарки</div>""",
                    unsafe_allow_html=True
                )

            st.text_input(
                "Статус профиля",
                key="teacher_status_input",
                value=st.session_state.teacher_status_saved,
                placeholder="Например: Готовлю финальный модуль"
            )
            st.text_area(
                "О себе",
                key="teacher_bio_input",
                value=st.session_state.teacher_bio_saved,
                height=110,
                placeholder="Коротко о вашей преподавательской стратегии..."
            )
            st.toggle("Публичный профиль", key="profile_public")
            if st.button("Сохранить профиль", type="secondary"):
                st.session_state.teacher_status_saved = st.session_state.teacher_status_input.strip()
                st.session_state.teacher_bio_saved = st.session_state.teacher_bio_input.strip()
                st.session_state.profile_public_saved = st.session_state.profile_public
                st.success("Профиль обновлён.")

            st.markdown("### ⚡ Быстрые действия")
            qa1, qa2 = st.columns(2)
            with qa1:
                if st.button("➕ Новая задача", use_container_width=True):
                    st.session_state.teacher_menu_selection = "⚡ Создать задачу"
                    st.rerun()
            with qa2:
                if st.button("📋 Смотреть работы", use_container_width=True):
                    st.session_state.teacher_menu_selection = "📋 Результаты"
                    st.rerun()

            st.selectbox(
                "Режим кабинета",
                ["🎯 Focus mode", "🤝 Mentor mode", "⚡ Sprint mode"],
                key="teacher_workspace_mode"
            )

        with right_col:
            st.markdown(
                f"""<div class="cabinet-hero">
                <div class="cabinet-hero-title">{teacher_username}</div>
                <div class="cabinet-hero-subtitle">{st.session_state.teacher_status_saved}</div>
                <div class="cabinet-hero-note">Уровень {profile['level']} · XP: {profile['xp']} / {profile['next_level_xp']} · Профиль: {"публичный" if st.session_state.profile_public_saved else "приватный"}</div>
                </div>""",
                unsafe_allow_html=True
            )
            st.progress(profile["level_progress"], text=f"Прогресс уровня: {int(profile['level_progress'] * 100)}%")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("🧪 Всего задач", profile["total_exams"])
            m2.metric("📨 Работ проверено", total_submissions)
            m3.metric("🔥 Индекс активности", profile["activity_index"])
            m4.metric("⭐ Impact score", profile["impact_score"])

            st.markdown("### 🎯 Цели кабинета")
            goal_col1, goal_col2 = st.columns(2)
            with goal_col1:
                weekly_exam_goal = st.slider("Цель по задачам", 1, 20, 6, key="weekly_exam_goal")
                weekly_result_goal = st.slider("Цель по проверкам", 1, 50, 12, key="weekly_result_goal")
            with goal_col2:
                exam_goal_progress = min(1.0, profile["total_exams"] / max(1, weekly_exam_goal))
                result_goal_progress = min(1.0, total_submissions / max(1, weekly_result_goal))
                combined = int(((exam_goal_progress + result_goal_progress) / 2) * 100)
                st.progress(exam_goal_progress, text=f"Задачи: {int(exam_goal_progress * 100)}%")
                st.progress(result_goal_progress, text=f"Работы: {int(result_goal_progress * 100)}%")
                st.markdown(f'<div class="goal-chip">Общий прогресс недели: {combined}%</div>', unsafe_allow_html=True)

            st.markdown("### 🏅 Достижения")
            achievement_cards = []
            for badge, unlocked, rule in achievements:
                status_cls = "badge-on" if unlocked else "badge-off"
                status_text = "Открыто" if unlocked else f"Цель: {rule}"
                achievement_cards.append(
                    f'<div class="achievement-card {status_cls}"><div>{badge}</div><small>{status_text}</small></div>'
                )
            st.markdown(f'<div class="achievement-grid">{"".join(achievement_cards)}</div>', unsafe_allow_html=True)

            st.markdown("### 🔔 Центр уведомлений")
            notifications = []
            if not all_teacher_exams:
                notifications.append("✨ Начните с первой задачи — это откроет прогресс в достижениях.")
            if total_submissions == 0:
                notifications.append("📥 Пока нет отправок. Поделитесь кодом доступа с учениками.")
            if stats.get("MYP", 0) == 0:
                notifications.append("🎓 Добавьте MYP задачу, чтобы расширить формат оценивания.")
            notifications.append(f"🚀 Активный режим: {st.session_state.teacher_workspace_mode}")
            for note in notifications:
                st.markdown(f"- {note}")

            st.markdown("### 📚 Мои экзамены")
            if not all_teacher_exams:
                st.caption("Пока нет опубликованных задач.")
            else:
                exam_rows = [
                    {
                        "Код": exam_code,
                        "Название": exam_title,
                        "Тип": exam_type,
                        "Время (мин)": str(exam_time) if exam_time else "Неограниченно",
                    }
                    for exam_code, exam_title, exam_type, exam_time in all_teacher_exams
                ]
                st.dataframe(pd.DataFrame(exam_rows), use_container_width=True, hide_index=True)

    elif menu_selection == "⚡ Создать задачу":
        st.header("⚡ Конструктор задач")

        # ── STEP 1: choose task type ─────────────────────────────────────────
        st.markdown("### Шаг 1 — Выберите тип задачи")
        type_cols = st.columns(3)
        type_map = {
            "⚡ Quick": ("Quick", "Быстрое эссе / краткий ответ. Одна рубрика, простая настройка."),
            "🎓 MYP": ("MYP", "Официальный формат IB MYP с предметными критериями A/B/C/D."),
            "🛠 Custom": ("Custom", "Полностью кастомная задача с загрузкой условий и рубрик."),
        }
        for col, (label, (val, tip)) in zip(type_cols, type_map.items()):
            with col:
                selected_style = "background:rgba(161,140,209,0.25); border:2px solid #a18cd1;" if st.session_state.task_type_sel == val else "background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.15);"
                st.markdown(f"""<div style="padding:16px; border-radius:14px; {selected_style} margin-bottom:8px;">
                    <b style="font-size:17px;">{label}</b><br>
                    <span style="font-size:12px; opacity:0.75;">{tip}</span>
                </div>""", unsafe_allow_html=True)
                if st.button(f"Выбрать {val}", key=f"sel_{val}", type="secondary"):
                    st.session_state.task_type_sel = val
                    st.session_state.ai_criteria_result = ""
                    st.session_state["wizard_criteria"] = ""
                    st.session_state.myp_tasks = [{"text": "", "active": True, "id": 0}]
                    st.session_state.myp_task_counter = 1
                    st.session_state.myp_success_criteria = {}
                    for ltr in ["A", "B", "C", "D"]:
                        st.session_state.pop(f"sc_{ltr}", None)
                        st.session_state.pop(f"myp_crit_{ltr}", None)
                    st.rerun()

        task_variant = st.session_state.task_type_sel
        if task_variant is None:
            st.info("👆 Нажмите на кнопку «Выбрать», чтобы начать создание задачи.")
        elif task_variant == "MYP":
            # ════════════════════════════════════════════════════════════
            # MYP WIZARD — 9 шагов
            # ════════════════════════════════════════════════════════════
            st.markdown("---")

            # ── Шаг 1: Код + Название ────────────────────────────────────
            st.markdown("#### 1️⃣ Название задачи")
            col_c1, col_c2 = st.columns([3, 1])
            with col_c1:
                nc = st.text_input("🔑 Код доступа", value=st.session_state.gen_code, key="myp_code")
            with col_c2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🎲 Сгенерировать код", key="myp_gen_code", type="secondary"):
                    st.session_state.gen_code = generate_random_code("MYP")
                    st.rerun()
            nt = st.text_input("📌 Название задачи", key="myp_title_input")

            # ── Шаг 2: Предмет ───────────────────────────────────────────
            st.markdown("---")
            st.markdown("#### 2️⃣ Выбор предмета")
            myp_subject = st.selectbox(
                "🏫 Предмет MYP",
                list(MYP_SUBJECT_CRITERIA.keys()),
                key="myp_subject_sel"
            )
            subject_criteria = MYP_SUBJECT_CRITERIA.get(myp_subject, MYP_SUBJECT_CRITERIA["Не указано"])

            # ── Шаг 3: Выбор критериев ───────────────────────────────────
            st.markdown("---")
            st.markdown("#### 3️⃣ Выбор критериев оценивания")
            st.caption("Выберите один или несколько критериев:")
            crit_cols = st.columns(4)
            active_criteria = []
            for col_w, (letter, name) in zip(crit_cols, subject_criteria.items()):
                with col_w:
                    is_sel = st.checkbox(
                        f"**{letter}** — {name}",
                        value=st.session_state.get(f"myp_crit_{letter}", False),
                        key=f"myp_crit_{letter}"
                    )
                    if is_sel:
                        active_criteria.append(letter)

            # ── Шаг 4: Условие задачи и список заданий ───────────────────
            st.markdown("---")
            st.markdown("#### 4️⃣ Условие задачи и список заданий")
            task_file = st.file_uploader(
                "📎 Файл с условием (.docx / .txt)",
                type=["docx", "txt"],
                key="myp_task_file"
            )
            conditions_text = st.text_area(
                "📝 Текст условия задачи",
                height=150,
                key="myp_conditions",
                placeholder="Опишите контекст, условие или вводную информацию..."
            )

            st.markdown("**📋 Список заданий:**")
            st.caption("Отметьте галочкой задания, которые войдут в экзамен:")

            # Initialize task list
            if not st.session_state.myp_tasks:
                st.session_state.myp_tasks = [{"text": "", "active": True, "id": 0}]
                st.session_state.myp_task_counter = 1

            to_delete = None
            for i, task in enumerate(st.session_state.myp_tasks):
                task_id = task["id"]
                # Init session state keys if not yet present
                if f"task_text_{task_id}" not in st.session_state:
                    st.session_state[f"task_text_{task_id}"] = task["text"]
                if f"task_active_{task_id}" not in st.session_state:
                    st.session_state[f"task_active_{task_id}"] = task["active"]
                tc1, tc2, tc3 = st.columns([0.5, 5.5, 0.5])
                with tc1:
                    st.checkbox("", key=f"task_active_{task_id}", label_visibility="collapsed")
                with tc2:
                    st.text_input(
                        "", key=f"task_text_{task_id}",
                        placeholder=f"Задание {i+1}...",
                        label_visibility="collapsed"
                    )
                with tc3:
                    if st.button("🗑", key=f"task_del_{task_id}", type="secondary"):
                        to_delete = i
            if to_delete is not None:
                st.session_state.myp_tasks.pop(to_delete)
                st.rerun()

            if st.button("➕ Добавить задание", type="secondary", key="myp_add_task"):
                new_id = st.session_state.myp_task_counter
                st.session_state.myp_tasks.append({"text": "", "active": True, "id": new_id})
                st.session_state[f"task_text_{new_id}"] = ""
                st.session_state[f"task_active_{new_id}"] = True
                st.session_state.myp_task_counter += 1
                st.rerun()

            # ── Шаг 5: Критерии успеха для каждого критерия ─────────────
            st.markdown("---")
            st.markdown("#### 5️⃣ Критерии успеха для каждого критерия")
            if not active_criteria:
                st.warning("⚠️ Сначала выберите критерии в шаге 3.")
            else:
                for letter in active_criteria:
                    crit_name = subject_criteria.get(letter, f"Критерий {letter}")
                    st.markdown(f"**Критерий {letter}: {crit_name}**")
                    sc_col1, sc_col2 = st.columns([5, 1])
                    with sc_col1:
                        if f"sc_{letter}" not in st.session_state:
                            st.session_state[f"sc_{letter}"] = st.session_state.myp_success_criteria.get(letter, "")
                        pending_key = f"sc_pending_{letter}"
                        if pending_key in st.session_state:
                            st.session_state[f"sc_{letter}"] = st.session_state.pop(pending_key)
                        st.text_area(
                            f"Критерии успеха {letter}",
                            key=f"sc_{letter}",
                            height=120,
                            placeholder=f"Что студент должен продемонстрировать для критерия {letter}...",
                            label_visibility="collapsed"
                        )
                    with sc_col2:
                        st.markdown("<br><br>", unsafe_allow_html=True)
                        if st.button(
                            "🤖 AI",
                            key=f"ai_sc_{letter}",
                            type="secondary",
                            help=f"Сгенерировать критерии успеха для {letter} с помощью AI"
                        ):
                            try:
                                with st.spinner(f"AI генерирует критерии {letter}..."):
                                    ai_sc = generate_criteria_with_ai(
                                        nt.strip() or "Без названия",
                                        conditions_text.strip() or "Описание не указано",
                                        "MYP",
                                        subject=f"{myp_subject} — Критерий {letter}: {crit_name}"
                                    )
                                st.session_state[f"sc_pending_{letter}"] = ai_sc
                                st.rerun()
                            except Exception:
                                st.error("⚠️ Операция не прошла. Попробуйте ещё раз.")

            # ── Шаг 6: Максимальный балл ─────────────────────────────────
            st.markdown("---")
            st.markdown("#### 6️⃣ Максимальный балл")
            auto_max = len(active_criteria) * 8
            if auto_max > 0:
                st.caption(f"Авто-расчёт: {len(active_criteria)} критери(я/ев) × 8 = {auto_max} баллов")
            myp_max_score = st.number_input(
                "Максимальный балл",
                min_value=1, max_value=200,
                value=max(auto_max, 8),
                key="myp_max_score_input"
            )

            # ── Шаг 7: Время (tech style) ────────────────────────────────
            st.markdown("---")
            st.markdown("#### 7️⃣ Время для экзамена")
            st.markdown(
                """<div style="background:rgba(123,227,255,0.06); border:1px solid rgba(123,227,255,0.35);
                border-radius:12px; padding:14px 18px; margin-bottom:10px;">
                <span style="color:#7be3ff; font-size:12px; font-weight:800; letter-spacing:3px;">
                ⏱ ТАЙМЕР ЭКЗАМЕНА</span></div>""",
                unsafe_allow_html=True
            )
            time_preset_cols = st.columns(6)
            time_presets_v = [0, 20, 30, 45, 60, 90]
            time_labels_v = ["∞ Без лим.", "20 мин", "30 мин", "45 мин", "60 мин", "90 мин"]
            for tp_col, tp_val, tp_lab in zip(time_preset_cols, time_presets_v, time_labels_v):
                with tp_col:
                    if st.button(tp_lab, key=f"myp_tp_{tp_val}", type="secondary"):
                        st.session_state["myp_time_val"] = tp_val
            t_limit = st.number_input(
                "Минуты (0 = без ограничений)",
                min_value=0, max_value=300,
                value=st.session_state.get("myp_time_val", 45),
                key="myp_time_input"
            )

            # ── Шаг 8: Строгость ИИ ──────────────────────────────────────
            st.markdown("---")
            st.markdown("#### 8️⃣ Строгость ИИ")
            diff_cols_m = st.columns(3)
            diff_map_m = {"🟢 Мягко": 3, "🟡 Средне": 5, "🔴 Строго": 8}
            for d_col, (d_lab, d_val) in zip(diff_cols_m, diff_map_m.items()):
                with d_col:
                    if st.button(d_lab, key=f"myp_diff_{d_val}", type="secondary"):
                        st.session_state["myp_strict_val"] = d_val
            strictness = st.slider(
                "Строгость оценивания (1-10)",
                min_value=1, max_value=10,
                value=st.session_state.get("myp_strict_val", 5),
                key="myp_strictness_slider"
            )

            # ── Шаг 9: Замечания учителя ─────────────────────────────────
            st.markdown("---")
            st.markdown("#### 9️⃣ Замечания учителя")
            teacher_notes = st.text_area(
                "Дополнительные инструкции для студентов",
                height=100,
                key="myp_teacher_notes",
                placeholder="Например: Используйте полные предложения. Минимальный объём — 500 слов..."
            )

            # ── Публикация ────────────────────────────────────────────────
            st.markdown("---")
            if st.button("🚀 Опубликовать MYP задачу", type="primary"):
                if not nt.strip():
                    st.warning("Укажите название задачи.")
                elif not nc.strip():
                    st.warning("Укажите код доступа.")
                elif not active_criteria:
                    st.warning("Выберите хотя бы один критерий оценивания (шаг 3).")
                else:
                    conditions_final = conditions_text.strip()
                    if task_file:
                        file_content = read_file(task_file)
                        if file_content:
                            conditions_final = (conditions_final + "\n\n" + file_content).strip()

                    active_tasks = []
                    for task in st.session_state.myp_tasks:
                        tid = task["id"]
                        txt = st.session_state.get(f"task_text_{tid}", "").strip()
                        act = st.session_state.get(f"task_active_{tid}", True)
                        if txt and act:
                            active_tasks.append({"text": txt})

                    myp_desc = json.dumps({
                        "conditions": conditions_final,
                        "tasks": active_tasks,
                        "teacher_notes": teacher_notes,
                    }, ensure_ascii=False)

                    myp_crit = json.dumps({
                        "subject": myp_subject,
                        "selected": active_criteria,
                        "criteria_names": {k: subject_criteria[k] for k in active_criteria},
                        "success": {k: st.session_state.get(f"sc_{k}", "") for k in active_criteria},
                        "max_score": int(myp_max_score),
                    }, ensure_ascii=False)

                    saved, save_message = save_teacher_exam(
                        nc, "MYP", nt, myp_desc, myp_crit,
                        float(strictness), t_limit, teacher_id
                    )
                    if saved:
                        st.success(f"✅ MYP задача опубликована! Код доступа: **{nc}**")
                        st.session_state.task_type_sel = None
                        st.session_state.ai_criteria_result = ""
                        st.session_state.gen_code = ""
                        st.session_state.myp_tasks = [{"text": "", "active": True, "id": 0}]
                        st.session_state.myp_task_counter = 1
                        st.session_state.myp_success_criteria = {}
                        for letter in ["A", "B", "C", "D"]:
                            st.session_state.pop(f"sc_{letter}", None)
                            st.session_state.pop(f"myp_crit_{letter}", None)
                    else:
                        st.error(save_message)

        else:
            # ── Quick / Custom flow ───────────────────────────────────────
            st.markdown(f"---\n### Шаг 2 — Основная информация  *(тип: {task_variant})*")

            col_c1, col_c2 = st.columns([3, 1])
            with col_c1:
                nc = st.text_input("🔑 Код доступа", value=st.session_state.gen_code, key="wizard_code")
            with col_c2:
                st.markdown("<br>", unsafe_allow_html=True)
                prefix_map = {"Quick": "FAST", "Custom": "CSTM"}
                if st.button("🎲 Сгенерировать код", type="secondary"):
                    st.session_state.gen_code = generate_random_code(prefix_map[task_variant])
                    st.rerun()

            nt = st.text_input("📌 Название задачи", key="wizard_title")

            st.markdown("### Шаг 3 — Условие задачи")
            c_desc = st.text_area("📝 Текст задачи (поддерживает HTML)", height=130, key="wizard_desc")
            c_file = st.file_uploader("📎 Загрузить файл с условием (.docx / .txt)", type=["docx", "txt"])
            myp_subject = "Не указано"
            task_questions = ""

            # ── Criteria section with AI assist ─────────────────────────────
            st.markdown("### Шаг 4 — Критерии оценивания")
            st.markdown("Напишите критерии вручную или используйте кнопки AI-помощника:")

            ai_col1, ai_col2, ai_col3 = st.columns(3)
            with ai_col1:
                if st.button("🤖 Сгенерировать критерии (AI)", type="secondary"):
                    try:
                        task_title_for_ai = nt.strip() or "Без названия"
                        task_desc_for_ai = (c_desc or task_questions or "Описание не указано").strip()
                        with st.spinner("AI генерирует критерии..."):
                            result = generate_criteria_with_ai(
                                task_title_for_ai, task_desc_for_ai, task_variant,
                                subject=myp_subject
                            )
                            st.session_state.ai_criteria_result = result
                            st.session_state["wizard_criteria"] = result
                        st.rerun()
                    except Exception:
                        st.error("⚠️ Операция не прошла. Попробуйте ещё раз.")
            with ai_col2:
                if st.button("✨ Улучшить критерии (AI)", type="secondary"):
                    existing = st.session_state.get("wizard_criteria", st.session_state.ai_criteria_result).strip()
                    if existing:
                        try:
                            with st.spinner("AI улучшает критерии..."):
                                result = improve_criteria_with_ai(existing, task_variant)
                                st.session_state.ai_criteria_result = result
                                st.session_state["wizard_criteria"] = result
                            st.rerun()
                        except Exception:
                            st.error("⚠️ Операция не прошла. Попробуйте ещё раз.")
                    else:
                        st.warning("Сначала введите или сгенерируйте критерии.")
            with ai_col3:
                rubric_options = {
                    "Quick": "### Критерии оценивания (100 баллов)\n- **Содержание (40 б):** Полнота раскрытия темы\n- **Структура (30 б):** Логичность, введение и заключение\n- **Язык (30 б):** Грамотность и стиль изложения",
                    "MYP": "### Критерий A: Знание и понимание (0-8)\n- 7-8: Полное и глубокое знание\n- 5-6: Хорошее знание с некоторыми пробелами\n- 3-4: Базовое знание\n- 1-2: Ограниченное знание\n\n### Критерий B: Анализ (0-8)\n- 7-8: Развёрнутый анализ\n- 5-6: Достаточный анализ\n- 3-4: Поверхностный анализ\n- 1-2: Минимальный анализ",
                    "Custom": "### Рубрика оценивания (10 баллов за каждый критерий)\n- **Понимание темы (10 б)**\n- **Аргументация (10 б)**\n- **Структура (10 б)**\n- **Язык и оформление (10 б)**\n- **Оригинальность (10 б)**",
                }
                if st.button("📋 Шаблон рубрики", type="secondary"):
                    tmpl = rubric_options.get(task_variant, "")
                    st.session_state.ai_criteria_result = tmpl
                    st.session_state["wizard_criteria"] = tmpl
                    st.rerun()

            if st.session_state.ai_criteria_result:
                st.info("✅ AI сгенерировал критерии ниже. Вы можете отредактировать их.")

            crit_manual = st.text_area(
                "Критерии оценивания",
                value=st.session_state.ai_criteria_result,
                height=220,
                key="wizard_criteria",
                placeholder="Введите критерии вручную или используйте кнопки AI выше..."
            )

            # ── Settings ─────────────────────────────────────────────────────
            st.markdown("### Шаг 5 — Настройки")
            set_col1, set_col2 = st.columns(2)
            with set_col1:
                st.markdown("**⏱ Время на выполнение**")
                time_preset_cols = st.columns(5)
                time_presets = [0, 15, 30, 45, 60]
                time_labels = ["∞", "15м", "30м", "45м", "60м"]
                for tp_col, tp_val, tp_lab in zip(time_preset_cols, time_presets, time_labels):
                    with tp_col:
                        if st.button(tp_lab, key=f"tp_{tp_val}", type="secondary"):
                            st.session_state[f"wizard_time_val"] = tp_val
                t_limit = st.number_input(
                    "Минуты (0 = без ограничений)",
                    min_value=0, max_value=300,
                    value=st.session_state.get("wizard_time_val", 45),
                    help="0 = без ограничений"
                )
            with set_col2:
                st.markdown("**📊 Строгость оценивания**")
                diff_cols = st.columns(3)
                diff_map = {"🟢 Мягко": 3, "🟡 Средне": 5, "🔴 Строго": 8}
                for d_col, (d_lab, d_val) in zip(diff_cols, diff_map.items()):
                    with d_col:
                        if st.button(d_lab, key=f"diff_{d_val}", type="secondary"):
                            st.session_state["wizard_strict_val"] = d_val
                strictness = st.slider(
                    "Строгость (1-10)",
                    min_value=1, max_value=10,
                    value=st.session_state.get("wizard_strict_val", 5)
                )

            st.markdown("---")
            if st.button("🚀 Опубликовать задачу", type="primary"):
                if not nt.strip():
                    st.warning("Укажите название задачи.")
                elif not nc.strip():
                    st.warning("Укажите код доступа.")
                else:
                    file_desc = read_file(c_file)
                    desc_parts = [p for p in [c_desc.strip(), file_desc.strip()] if p]
                    final_desc = "<br>".join(desc_parts) or "Описание не указано."
                    final_crit = crit_manual.strip() or "Оценить по содержательности, структуре и аргументации."

                    saved, save_message = save_teacher_exam(nc, task_variant, nt, final_desc, final_crit, float(strictness), t_limit, teacher_id)
                    if saved:
                        st.success(f"✅ Задача опубликована! Код доступа: **{nc}**")
                        st.session_state.task_type_sel = None
                        st.session_state.ai_criteria_result = ""
                        st.session_state.gen_code = ""
                    else:
                        st.error(save_message)

    elif menu_selection == "📋 Результаты":
        st.header("📋 Результаты студентов")
        c = db_conn.cursor()
        c.execute("SELECT title FROM exams_v3 WHERE teacher_id=?", (teacher_id,))
        teacher_titles = [row[0] for row in c.fetchall()]
        if not teacher_titles:
            data = []
        else:
            placeholders, safe_titles = build_in_clause(teacher_titles)
            c.execute(f"SELECT name, title, essay, grade FROM submissions WHERE title IN ({placeholders})", safe_titles)
            data = c.fetchall()
        if data:
            df = pd.DataFrame(data, columns=["Имя", "Экзамен", "Эссе", "Оценка"])
            st.download_button("Скачать CSV", df.to_csv(index=False).encode('utf-8-sig'), "results.csv", type="primary")
            for r in reversed(data):
                with st.expander(f"{r[0]} — {r[1]}"):
                    st.markdown("**Ответ:**", unsafe_allow_html=True)
                    st.markdown(r[2], unsafe_allow_html=True)
                    st.info(f"**Оценка ИИ:**\n{r[3]}")
        else:
            st.info("Пока нет ни одной сданной работы.")

        st.markdown("---")
        st.subheader("❓ Вопросы от пользователей")
        if teacher_titles:
            placeholders, safe_titles = build_in_clause(teacher_titles)
            c.execute(
                f"SELECT student_name, exam_title, question, created_at FROM student_questions WHERE exam_title IN ({placeholders}) ORDER BY id DESC",
                safe_titles
            )
            question_data = c.fetchall()
        else:
            question_data = []
        if question_data:
            for q_name, q_exam, q_text, q_created in question_data:
                created_label = q_created or ""
                if q_created:
                    try:
                        created_label = datetime.fromisoformat(q_created).strftime("%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        created_label = q_created
                with st.expander(f"{q_name} — {q_exam} ({created_label})"):
                    st.markdown(q_text)
        else:
            st.info("Пока нет вопросов от пользователей.")

# ПАНЕЛЬ АДМИНИСТРАТОРА
elif st.session_state.role == "Admin":
    if st.session_state.teacher_id is None:
        st.session_state.role = None
        st.warning("Сессия администратора не найдена. Войдите снова.")
        st.rerun()

    admin_username = st.session_state.teacher_username

    with st.sidebar:
        st.markdown(f"""
        <div style="text-align:center; padding: 12px 0 8px 0;">
            <div style="font-size:36px;">🛡️</div>
            <div style="font-size:15px; color:#fbc2eb; font-weight:700;">{admin_username}</div>
            <div style="font-size:11px; color:rgba(255,255,255,0.5);">Administrator</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("---")
        admin_menu = st.radio(
            "Admin навигация:",
            ["👥 Все учителя", "📚 Все задачи", "📊 Все результаты"],
            label_visibility="collapsed"
        )
        admin_menu = admin_menu.split(" ", 1)[-1].strip()
        st.markdown("---")
        if st.button("🚪 Выйти", type="primary"):
            st.session_state.role = None
            st.session_state.teacher_id = None
            st.session_state.teacher_username = None
            st.query_params.clear()
            st.rerun()

    if admin_menu == "Все учителя":
        st.header("👥 Все зарегистрированные учителя")
        adm_c = db_conn.cursor()
        adm_c.execute("SELECT id, username, email, is_admin, created_at FROM teachers ORDER BY id")
        all_teachers = adm_c.fetchall()
        if all_teachers:
            df_t = pd.DataFrame(all_teachers, columns=["ID", "Username", "Email", "Администратор", "Дата регистрации"])
            df_t["Администратор"] = df_t["Администратор"].apply(lambda x: "✅ Да" if x else "Нет")
            st.dataframe(df_t, use_container_width=True)
            st.markdown("---")
            st.markdown("#### 🗑 Удалить учителя")
            del_col1, del_col2 = st.columns([2, 1])
            with del_col1:
                del_teacher_id = st.number_input("ID учителя для удаления", min_value=1, step=1, key="del_teacher_id")
            with del_col2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Удалить учителя", type="secondary"):
                    adm_c.execute("SELECT username, is_admin FROM teachers WHERE id=?", (del_teacher_id,))
                    target = adm_c.fetchone()
                    if target is None:
                        st.error("Учитель с таким ID не найден.")
                    elif target[1] == 1:  # is_admin flag
                        st.error("Нельзя удалить администратора.")
                    else:
                        adm_c.execute("DELETE FROM teachers WHERE id=?", (del_teacher_id,))
                        db_conn.commit()
                        st.success(f"Учитель «{target[0]}» удалён.")
                        st.rerun()
        else:
            st.info("Нет зарегистрированных учителей.")

    elif admin_menu == "Все задачи":
        st.header("📚 Все задачи на платформе")
        adm_c = db_conn.cursor()
        adm_c.execute("""
            SELECT e.code, e.title, e.type, e.time_limit, t.username
            FROM exams_v3 e
            LEFT JOIN teachers t ON e.teacher_id = t.id
            ORDER BY e.rowid DESC
        """)
        all_exams = adm_c.fetchall()
        if all_exams:
            df_e = pd.DataFrame(all_exams, columns=["Код", "Название", "Тип", "Время (мин)", "Учитель"])
            st.dataframe(df_e, use_container_width=True)
            st.markdown("---")
            st.markdown("#### 🗑 Удалить задачу по коду")
            del_exam_col1, del_exam_col2 = st.columns([2, 1])
            with del_exam_col1:
                del_code = st.text_input("Код задачи", key="del_exam_code")
            with del_exam_col2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Удалить задачу", type="secondary"):
                    adm_c.execute("SELECT title FROM exams_v3 WHERE code=?", (del_code.strip(),))
                    target_exam = adm_c.fetchone()
                    if target_exam:
                        adm_c.execute("DELETE FROM exams_v3 WHERE code=?", (del_code.strip(),))
                        db_conn.commit()
                        st.success(f"Задача «{target_exam[0]}» удалена.")
                        st.rerun()
                    else:
                        st.error("Задача с таким кодом не найдена.")
        else:
            st.info("Нет задач на платформе.")

    elif admin_menu == "Все результаты":
        st.header("📊 Все сданные работы")
        adm_c = db_conn.cursor()
        adm_c.execute("SELECT id, name, title, grade FROM submissions ORDER BY id DESC")
        all_subs = adm_c.fetchall()
        if all_subs:
            df_s = pd.DataFrame(all_subs, columns=["ID", "Имя ученика", "Экзамен", "Оценка AI"])
            st.download_button("📥 Скачать всё (CSV)", df_s.to_csv(index=False).encode('utf-8-sig'), "all_results.csv", type="primary")
            st.dataframe(df_s[["ID", "Имя ученика", "Экзамен", "Оценка AI"]], use_container_width=True)
            st.markdown("---")
            for sub_id, sub_name, sub_title, sub_grade in all_subs:
                with st.expander(f"#{sub_id} — {sub_name} | {sub_title}"):
                    st.info(f"**Оценка AI:**\n{sub_grade}")
                    adm_c2 = db_conn.cursor()
                    if st.button(f"🗑 Удалить запись #{sub_id}", key=f"del_sub_{sub_id}", type="secondary"):
                        adm_c2.execute("DELETE FROM submissions WHERE id=?", (sub_id,))
                        db_conn.commit()
                        st.success(f"Запись #{sub_id} удалена.")
                        st.rerun()
        else:
            st.info("Нет сданных работ.")

# СТУДЕНТ
elif st.session_state.role == "Student":
    exam = st.session_state.current_exam
    is_time_up = False
    remaining_seconds = 0
    
    # Считаем время
    if st.session_state.exam_end_time and not st.session_state.exam_submitted:
        remaining_seconds = int(st.session_state.exam_end_time - time.time())
        if remaining_seconds <= 0:
            is_time_up = True

    # Парсим JSON для MYP
    myp_desc_data = None
    myp_crit_data = None
    if exam["type"] == "MYP":
        try:
            myp_desc_data = json.loads(exam["desc"])
            if not isinstance(myp_desc_data, dict):
                myp_desc_data = None
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            myp_crit_data = json.loads(exam["criteria"])
            if not isinstance(myp_crit_data, dict):
                myp_crit_data = None
        except (json.JSONDecodeError, TypeError):
            pass

    # Заголовок
    mode_label = "Режим IB MYP" if exam["type"] == "MYP" else ("Кастомный режим" if exam["type"] == "Custom" else "Стандартный режим")
    st.markdown(f'<p style="color: #a18cd1; font-weight: bold; margin-bottom: 0;">{mode_label}</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="logo-text" style="font-size: 32px !important; margin-top: 0;">{exam["title"]}</p>', unsafe_allow_html=True)

    # Прокторинг — только во время активного экзамена
    if not st.session_state.exam_submitted:
        components.html(
            """
            <script>
                const doc = window.parent.document;
                if (!doc.getElementById("proctoring-style")) {
                    const style = doc.createElement("style");
                    style.id = "proctoring-style";
                    style.textContent = "#proctoring-alert{position:fixed;right:18px;bottom:18px;z-index:999999;padding:10px 14px;border-radius:10px;background:rgba(255,75,75,.92);color:#fff;font-weight:700;display:none;box-shadow:0 6px 16px rgba(0,0,0,.4);}#proctoring-indicator{position:fixed;right:18px;top:18px;z-index:999999;padding:8px 12px;border-radius:999px;background:rgba(20,20,38,.9);color:#7be3ff;border:1px solid rgba(123,227,255,.65);font-size:12px;font-weight:700;}";
                    doc.head.appendChild(style);
                }
                if (!doc.getElementById("proctoring-alert")) {
                    const alertBox = doc.createElement("div");
                    alertBox.id = "proctoring-alert";
                    doc.body.appendChild(alertBox);
                }
                if (!doc.getElementById("proctoring-indicator")) {
                    const indicator = doc.createElement("div");
                    indicator.id = "proctoring-indicator";
                    indicator.innerText = "PROCTORING ACTIVE";
                    doc.body.appendChild(indicator);
                }
                window.proctoringViolations = window.proctoringViolations || 0;
                function showProctoringWarning(message){
                    const alertBox = doc.getElementById("proctoring-alert");
                    window.proctoringViolations += 1;
                    alertBox.innerText = `Прокторинг: ${message}. Нарушений: ${window.proctoringViolations}`;
                    alertBox.style.display = "block";
                    clearTimeout(window.proctoringTimer);
                    window.proctoringTimer = setTimeout(()=>{ alertBox.style.display = "none"; }, 3000);
                }
                if (!window.proctoringEventsAttached) {
                    window.proctoringEventsAttached = true;
                    doc.addEventListener("visibilitychange", () => {
                        if (doc.hidden) showProctoringWarning("обнаружено переключение вкладки");
                    });
                    window.parent.addEventListener("blur", () => {
                        showProctoringWarning("обнаружен выход из окна экзамена");
                    });
                    doc.addEventListener("copy", (e) => {
                        e.preventDefault();
                        showProctoringWarning("копирование заблокировано");
                    });
                    doc.addEventListener("paste", (e) => {
                        e.preventDefault();
                        showProctoringWarning("вставка заблокирована");
                    });
                    doc.addEventListener("contextmenu", (e) => {
                        e.preventDefault();
                        showProctoringWarning("контекстное меню заблокировано");
                    });
                }
            </script>
            """,
            height=0
        )
    else:
        # Скрываем индикатор прокторинга после сдачи
        components.html(
            """<script>
            const ind = window.parent.document.getElementById("proctoring-indicator");
            if (ind) ind.style.display = "none";
            </script>""",
            height=0
        )
    
    col_left, col_right = st.columns([1.5, 1])
    
    with col_left:
        st.markdown("### Условие задачи")
        with st.container(height=400):
            if myp_desc_data:
                if myp_desc_data.get("conditions"):
                    st.markdown(myp_desc_data["conditions"], unsafe_allow_html=True)
                if myp_desc_data.get("tasks"):
                    st.markdown("**Задания:**")
                    for i, task in enumerate(myp_desc_data["tasks"], 1):
                        st.markdown(f"{i}. {task['text']}")
                if myp_desc_data.get("teacher_notes"):
                    st.info(f"📌 Замечания учителя: {myp_desc_data['teacher_notes']}")
            else:
                st.markdown(exam["desc"], unsafe_allow_html=True)
        
        if st.session_state.exam_submitted:
            st.success("Вы успешно сдали эту работу! Повторная отправка невозможна.")
            st.markdown(st.session_state.student_grade)
            if st.button("Выйти на главную", type="secondary"):
                st.session_state.role = None
                st.session_state.exam_submitted = False
                st.session_state.student_draft = ""
                st.session_state.exam_end_time = None
                st.query_params.clear()
                st.rerun()
                
        else:
            st.markdown("### Ваш ответ")
            s_name = st.text_input("Ваше полное имя (Имя и Фамилия)")
            
            s_essay = st.text_area(
                "Напишите ваш ответ здесь... (сохраняется автоматически)", 
                value=st.session_state.student_draft,
                height=500, 
                key="essay_input",
                on_change=update_draft,
                disabled=is_time_up
            )
            
            if is_time_up:
                st.error("Время, отведенное на экзамен, закончилось.")
            
            col_bt1, col_bt2 = st.columns(2)
            with col_bt1:
                if st.button("Отправить работу", type="primary", disabled=is_time_up):
                    if s_name and len(s_essay.strip()) > 0:
                        c = db_conn.cursor()
                        c.execute("SELECT id FROM submissions WHERE name=? AND title=?", (s_name, exam['title']))
                        
                        if c.fetchone():
                            st.error(f"Ученик '{s_name}' уже сдавал этот экзамен.")
                        else:
                            try:
                                with st.spinner("AI анализирует ваш ответ..."):
                                    grade = grade_essay(exam['title'], exam['desc'], exam['criteria'], exam['strictness'], s_essay, exam["type"])
                                    c.execute("INSERT INTO submissions (name, title, essay, grade) VALUES (?,?,?,?)", (s_name, exam['title'], s_essay, grade))
                                    db_conn.commit()
                                    
                                    st.session_state.exam_submitted = True
                                    st.session_state.student_grade = grade
                                    st.rerun()
                            except Exception:
                                st.error("⚠️ Операция не прошла. Попробуйте ещё раз.")
                    else: 
                        st.warning("Пожалуйста, заполните имя и напишите ответ.")
            with col_bt2:
                if st.button("Выйти на главную", type="secondary"):
                    st.session_state.role = None
                    st.session_state.student_draft = ""
                    st.session_state.exam_end_time = None 
                    st.query_params.clear()
                    st.rerun()

            st.markdown("### ❓ Вопрос к учителю")
            question_name = st.text_input(
                "Ваше имя для вопроса",
                value=s_name,
                key="student_question_name",
                placeholder="Имя и Фамилия"
            )
            student_question = st.text_area(
                "Если что-то непонятно — задайте вопрос",
                key="student_question_input",
                height=120,
                placeholder="Напишите ваш вопрос по заданию..."
            )
            if st.button("Отправить вопрос", type="secondary"):
                if not question_name.strip():
                    st.warning("Укажите ваше имя для вопроса.")
                elif not student_question.strip():
                    st.warning("Напишите текст вопроса.")
                elif s_name.strip() and question_name.strip() != s_name.strip():
                    st.warning("Имя в вопросе должно совпадать с именем в вашем ответе.")
                else:
                    c = db_conn.cursor()
                    c.execute(
                        "INSERT INTO student_questions (student_name, exam_title, question) VALUES (?,?,?)",
                        (question_name.strip(), exam['title'], student_question.strip())
                    )
                    db_conn.commit()
                    st.success("Вопрос отправлен учителю.")

    with col_right:
        if not st.session_state.exam_submitted:
            st.markdown("### Прокторинг")
            st.info("Активирован базовый прокторинг: фиксируются выход из вкладки/окна, копирование, вставка и контекстное меню.")

        st.markdown("### Критерии оценивания")
        with st.container(height=450):
            if myp_crit_data:
                st.markdown(f"**Предмет:** {myp_crit_data.get('subject', '')}")
                st.markdown(f"**Макс. балл:** {myp_crit_data.get('max_score', '')}")
                st.markdown("---")
                for letter in myp_crit_data.get("selected", []):
                    crit_name = myp_crit_data.get("criteria_names", {}).get(letter, "")
                    success = myp_crit_data.get("success", {}).get(letter, "")
                    st.markdown(f"**Критерий {letter}: {crit_name}**")
                    if success:
                        st.markdown(success)
                    st.markdown("---")
            else:
                st.markdown(exam["criteria"], unsafe_allow_html=True)
            
        st.markdown("---")
        
        # ТАЙМЕР — только во время экзамена
        if st.session_state.exam_end_time and not st.session_state.exam_submitted:
            if not is_time_up:
                end_time_ms = int(st.session_state.exam_end_time * 1000)
                
                timer_html = f"""
                <div id="exam-timer" style="font-family: sans-serif; font-size: 20px; font-weight: bold; color: #ff4b4b; background: rgba(255, 75, 75, 0.1); padding: 15px; border-radius: 8px; border: 2px solid #ff4b4b; text-align: center;">
                ⏳ Вычисление времени...
                </div>
                <script>
                var endTime = {end_time_ms};
                var timerInterval = setInterval(function() {{
                    var now = new Date().getTime();
                    var distance = endTime - now;
                    
                    if (distance <= 0) {{
                        clearInterval(timerInterval);
                        document.getElementById("exam-timer").innerHTML = "⏰ Время вышло!";
                    }} else {{
                        var m = Math.floor(distance / (1000 * 60));
                        var s = Math.floor((distance % (1000 * 60)) / 1000);
                        if (s < 10) {{ s = "0" + s; }}
                        document.getElementById("exam-timer").innerHTML = "⏳ Осталось: " + m + ":" + s;
                    }}
                }}, 1000);
                </script>
                """
                components.html(timer_html, height=80)
            else:
                st.markdown("""
                <div style="font-size: 20px; font-weight: bold; color: #ff4b4b; background: rgba(255, 75, 75, 0.1); padding: 15px; border-radius: 8px; border: 2px solid #ff4b4b; text-align: center;">
                ⏰ Время вышло!
                </div>
                """, unsafe_allow_html=True)
