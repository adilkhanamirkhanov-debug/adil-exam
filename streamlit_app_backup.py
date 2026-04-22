import streamlit as st
import sqlite3
import pandas as pd
from openai import OpenAI
import random
import string
import time 
import re
import mammoth 
import streamlit.components.v1 as components
from werkzeug.security import generate_password_hash, check_password_hash

EMAIL_VALIDATION_PATTERN = r"^(?![.])(?!.*[.]{2})[A-Za-z0-9._%+-]+(?<![.])@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"

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
        menu_selection = st.radio(
            "Навигация:",
            ["📊 Дашборд", "⚡ Создать задачу", "📋 Результаты"],
            label_visibility="collapsed"
        )
        menu_selection = menu_selection.split(" ", 1)[-1].strip()
        st.markdown("---")
        if st.button("🚪 Выйти", type="primary"):
            st.session_state.role = None
            st.session_state.teacher_id = None
            st.session_state.teacher_username = None
            st.session_state.task_step = 1
            st.session_state.task_type_sel = None
            st.query_params.clear()
            st.rerun()

    if menu_selection == "Дашборд":
        st.header("📊 Профиль и статистика")
        stats, total_submissions = get_teacher_stats(teacher_id)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("⚡ Quick задач", stats.get("Quick", 0))
        c2.metric("🎓 MYP задач", stats.get("MYP", 0))
        c3.metric("🛠 Custom задач", stats.get("Custom", 0))
        c4.metric("📨 Сданных работ", total_submissions)
        st.info("Здесь отображаются только ваши экзамены и связанные результаты.")
        st.markdown("### Мои экзамены")
        all_teacher_exams = get_teacher_exams(teacher_id)
        if not all_teacher_exams:
            st.caption("Пока нет опубликованных задач.")
        for exam_code, exam_title, exam_type, exam_time in all_teacher_exams:
            st.markdown(f"- **{exam_title}** (`{exam_type}`) — код: `{exam_code}`, время: {exam_time} мин.")

    elif menu_selection == "Создать задачу":
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
                    st.rerun()

        task_variant = st.session_state.task_type_sel
        if task_variant is None:
            st.info("👆 Нажмите на кнопку «Выбрать», чтобы начать создание задачи.")
        else:
            st.markdown(f"---\n### Шаг 2 — Основная информация  *(тип: {task_variant})*")

            # ── Code generation row ──────────────────────────────────────────
            col_c1, col_c2 = st.columns([3, 1])
            with col_c1:
                nc = st.text_input("🔑 Код доступа", value=st.session_state.gen_code, key="wizard_code")
            with col_c2:
                st.markdown("<br>", unsafe_allow_html=True)
                prefix_map = {"Quick": "FAST", "MYP": "MYP", "Custom": "CSTM"}
                if st.button("🎲 Сгенерировать код", type="secondary"):
                    st.session_state.gen_code = generate_random_code(prefix_map[task_variant])
                    st.rerun()

            nt = st.text_input("📌 Название задачи", key="wizard_title")

            # ── Type-specific fields ─────────────────────────────────────────
            if task_variant == "MYP":
                st.markdown("### Шаг 3 — Предмет и условие")
                myp_subject = st.selectbox("🏫 Предмет MYP", [
                    "Не указано", "Науки (Sciences)", "Математика (Mathematics)",
                    "Язык и литература", "Приобретение языка", "Индивидуумы и общества",
                    "Дизайн (Design)", "Искусство (Arts)", "Физкультура и здоровье (PHE)"
                ])
                task_file = st.file_uploader("📎 Файл с условием (.docx / .txt)", type=["docx", "txt"])
                task_questions = st.text_area("❓ Дополнительные вопросы (каждый с новой строки)", height=130)
                crit_file = st.file_uploader("📎 Файл с рубрикой (необязательно)", type=["docx", "txt"])
                c_desc = ""
                c_file = None
            else:
                st.markdown("### Шаг 3 — Условие задачи")
                c_desc = st.text_area("📝 Текст задачи (поддерживает HTML)", height=130, key="wizard_desc")
                c_file = st.file_uploader("📎 Загрузить файл с условием (.docx / .txt)", type=["docx", "txt"])
                myp_subject = "Не указано"
                task_questions = ""
                task_file = None
                crit_file = None

            # ── Criteria section with AI assist ─────────────────────────────
            st.markdown("### Шаг 4 — Критерии оценивания")
            st.markdown("Напишите критерии вручную или используйте кнопки AI-помощника:")

            ai_col1, ai_col2, ai_col3 = st.columns(3)
            with ai_col1:
                if st.button("🤖 Сгенерировать критерии (AI)", type="secondary"):
                    task_title_for_ai = nt.strip() or "Без названия"
                    task_desc_for_ai = (c_desc or task_questions or "Описание не указано").strip()
                    with st.spinner("AI генерирует критерии..."):
                        st.session_state.ai_criteria_result = generate_criteria_with_ai(
                            task_title_for_ai, task_desc_for_ai, task_variant,
                            subject=myp_subject
                        )
                    st.rerun()
            with ai_col2:
                if st.button("✨ Улучшить критерии (AI)", type="secondary"):
                    existing = st.session_state.ai_criteria_result.strip()
                    if existing:
                        with st.spinner("AI улучшает критерии..."):
                            st.session_state.ai_criteria_result = improve_criteria_with_ai(existing, task_variant)
                        st.rerun()
                    else:
                        st.warning("Сначала введите или сгенерируйте критерии.")
            with ai_col3:
                rubric_options = {
                    "Quick": "### Критерии оценивания (100 баллов)\n- **Содержание (40 б):** Полнота раскрытия темы\n- **Структура (30 б):** Логичность, введение и заключение\n- **Язык (30 б):** Грамотность и стиль изложения",
                    "MYP": "### Критерий A: Знание и понимание (0-8)\n- 7-8: Полное и глубокое знание\n- 5-6: Хорошее знание с некоторыми пробелами\n- 3-4: Базовое знание\n- 1-2: Ограниченное знание\n\n### Критерий B: Анализ (0-8)\n- 7-8: Развёрнутый анализ\n- 5-6: Достаточный анализ\n- 3-4: Поверхностный анализ\n- 1-2: Минимальный анализ",
                    "Custom": "### Рубрика оценивания (10 баллов за каждый критерий)\n- **Понимание темы (10 б)**\n- **Аргументация (10 б)**\n- **Структура (10 б)**\n- **Язык и оформление (10 б)**\n- **Оригинальность (10 б)**",
                }
                if st.button("📋 Шаблон рубрики", type="secondary"):
                    st.session_state.ai_criteria_result = rubric_options.get(task_variant, "")
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
                    if task_variant == "MYP":
                        desc_content = read_file(task_file)
                        questions_html = f"<br><h3>Вопросы:</h3><p>{task_questions.replace(chr(10), '<br>')}</p>" if task_questions.strip() else ""
                        final_desc = desc_content + questions_html or "Смотрите вопросы."
                        subject_prefix = f"[ПРЕДМЕТ MYP: {myp_subject}]\n\n" if "Не указано" not in myp_subject else ""
                        final_crit = subject_prefix + (crit_manual.strip() or read_file(crit_file)) or "Оценивать по стандартам MYP."
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

    elif menu_selection == "Результаты":
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

    # Заголовок
    mode_label = "Режим IB MYP" if exam["type"] == "MYP" else ("Кастомный режим" if exam["type"] == "Custom" else "Стандартный режим")
    st.markdown(f'<p style="color: #a18cd1; font-weight: bold; margin-bottom: 0;">{mode_label}</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="logo-text" style="font-size: 32px !important; margin-top: 0;">{exam["title"]}</p>', unsafe_allow_html=True)

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
    
    col_left, col_right = st.columns([1.5, 1])
    
    with col_left:
        st.markdown("### Условие задачи")
        with st.container(height=400):
            st.markdown(exam["desc"], unsafe_allow_html=True)
        
        if st.session_state.exam_submitted:
            st.success("Вы успешно сдали эту работу! Повторная отправка невозможна.")
            st.markdown(st.session_state.student_grade)
            if st.button("Выйти на главную", type="secondary"):
                st.session_state.role = None
                st.session_state.exam_submitted = False
                st.session_state.student_draft = "" # Очищаем черновик
                st.session_state.exam_end_time = None
                st.query_params.clear() # Очищаем URL
                st.rerun()
                
        else:
            st.markdown("### Ваш ответ")
            s_name = st.text_input("Ваше полное имя (Имя и Фамилия)")
            
            # Поле для ответа с привязкой к черновику 
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
                            with st.spinner("AI анализирует ваш ответ..."):
                                grade = grade_essay(exam['title'], exam['desc'], exam['criteria'], exam['strictness'], s_essay, exam["type"])
                                c.execute("INSERT INTO submissions (name, title, essay, grade) VALUES (?,?,?,?)", (s_name, exam['title'], s_essay, grade))
                                db_conn.commit()
                                
                                st.session_state.exam_submitted = True
                                st.session_state.student_grade = grade
                                st.rerun()
                    else: 
                        st.warning("Пожалуйста, заполните имя и напишите ответ.")
            with col_bt2:
                # Очистка при ручном выходе
                if st.button("Выйти на главную", type="secondary"):
                    st.session_state.role = None
                    st.session_state.student_draft = "" # Полностью удаляем текст
                    st.session_state.exam_end_time = None 
                    st.query_params.clear() # Очищаем URL
                    st.rerun()

    with col_right:
        st.markdown("### Прокторинг")
        st.info("Активирован базовый прокторинг: фиксируются выход из вкладки/окна, копирование, вставка и контекстное меню.")

        st.markdown("### Критерии оценивания")
        with st.container(height=450):
            st.markdown(exam["criteria"], unsafe_allow_html=True)
            
        st.markdown("---")
        
        # ТАЙМЕР
        if st.session_state.exam_end_time and not st.session_state.exam_submitted:
            if not is_time_up:
                # Переводим время окончания в миллисекунды для JavaScript (оно неизменно!)
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
                        // Считаем минуты и секунды напрямую из разницы во времени
                        var m = Math.floor(distance / (1000 * 60));
                        var s = Math.floor((distance % (1000 * 60)) / 1000);
                        if (s < 10) {{ s = "0" + s; }}
                        document.getElementById("exam-timer").innerHTML = "⏳ Осталось: " + m + ":" + s;
                    }}
                }}, 1000);
                </script>
                """
                # Выводим таймер
                components.html(timer_html, height=80)
            else:
                st.markdown("""
                <div style="font-size: 20px; font-weight: bold; color: #ff4b4b; background: rgba(255, 75, 75, 0.1); padding: 15px; border-radius: 8px; border: 2px solid #ff4b4b; text-align: center;">
                ⏰ Время вышло!
                </div>
                """, unsafe_allow_html=True)
