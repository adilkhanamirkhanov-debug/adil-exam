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

# --- 1. CONFIG ---
st.set_page_config(
    page_title="AdilEduAssessment", 
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute("PRAGMA table_info(exams_v3)")
    exam_columns = [row[1] for row in c.fetchall()]
    if "teacher_id" not in exam_columns:
        c.execute("ALTER TABLE exams_v3 ADD COLUMN teacher_id INTEGER")
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

def register_teacher(username, email, password):
    password_clean = password.strip()
    email_clean = email.strip().lower()

    if len(username.strip()) < 3:
        return False, "Имя пользователя должно содержать минимум 3 символа."
    if len(password_clean) < 6:
        return False, "Пароль должен содержать минимум 6 символов."
    if not re.fullmatch(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", email_clean):
        return False, "Введите корректный email."

    try:
        c = db_conn.cursor()
        c.execute(
            "INSERT INTO teachers (username, password_hash, email) VALUES (?,?,?)",
            (username.strip(), generate_password_hash(password_clean), email_clean)
        )
        db_conn.commit()
        return True, "Регистрация успешна! Теперь вы можете войти."
    except sqlite3.IntegrityError:
        return False, "Пользователь с таким username/email уже существует."

def authenticate_teacher(login_input, password):
    c = db_conn.cursor()
    c.execute(
        "SELECT id, username, password_hash FROM teachers WHERE username=? OR email=?",
        (login_input.strip(), login_input.strip().lower())
    )
    teacher = c.fetchone()
    if teacher and check_password_hash(teacher[2], password.strip()):
        return teacher
    return None

def save_teacher_exam(code, exam_type, title, desc, criteria, strictness, time_limit, teacher_id):
    c = db_conn.cursor()
    c.execute("SELECT teacher_id FROM exams_v3 WHERE code=?", (code,))
    existing = c.fetchone()
    if existing and existing[0] not in (None, teacher_id):
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
    if titles:
        placeholders = ",".join(["?"] * len(titles))
        c.execute(f"SELECT COUNT(*) FROM submissions WHERE title IN ({placeholders})", titles)
        submissions_count = c.fetchone()[0]
    else:
        submissions_count = 0
    return type_counts, submissions_count

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

# --- 6. NAVIGATION ---

# ГЛАВНЫЙ ЭКРАН (ВХОД)
if st.session_state.role is None:
    with st.sidebar:
        st.markdown("### Teacher Space")
        login_tab, register_tab = st.tabs(["Вход", "Регистрация"])
        with login_tab:
            t_user = st.text_input("Username или Email")
            t_pass = st.text_input("Password", type="password")
            if st.button("Login", type="primary"):
                teacher = authenticate_teacher(t_user, t_pass)
                if teacher:
                    st.session_state.role = "Teacher"
                    st.session_state.teacher_id = teacher[0]
                    st.session_state.teacher_username = teacher[1]
                    st.query_params.clear() # Очищаем URL при входе учителя
                    st.rerun()
                else:
                    st.error("Неверный логин или пароль.")
        with register_tab:
            new_user = st.text_input("Новый username")
            new_email = st.text_input("Email")
            new_pass = st.text_input("Новый пароль", type="password")
            if st.button("Создать аккаунт", type="secondary"):
                success, message = register_teacher(new_user, new_email, new_pass)
                if success:
                    st.success(message)
                else:
                    st.warning(message)

    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown('<p class="logo-text">AdilEduAssessment</p>', unsafe_allow_html=True)
    st.markdown(
        """
        <div style="max-width: 980px; margin: 0 auto 24px auto; text-align: center; color: #e8d9ff;">
            <p style="font-size: 18px; margin-bottom: 4px;"><b>Интеллектуальная платформа для экзаменов и оценки ответов с AI</b></p>
            <p style="opacity: 0.85;">Учителя создают экзамены и кастомные задания, а ученики сдают работу по коду доступа.</p>
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
                    <li>Выберите тип экзамена</li>
                    <li>Введите код от учителя</li>
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
                    <li>Создавайте Quick/MYP/Custom задания</li>
                    <li>Отслеживайте статистику и результаты</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True
        )
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<p style='text-align: center; opacity: 0.7;'>Выберите формат сдачи и введите код доступа</p>", unsafe_allow_html=True)
        
        student_mode = st.radio("Режим экзамена:", ["Стандартный экзамен", "Экзамен MYP", "Кастомная задача"], horizontal=True)
        access_code = st.text_input("Код", placeholder="Например: MYP-1A2B3", label_visibility="collapsed")
        
        if st.button("Начать экзамен", type="primary"):
            c = db_conn.cursor()
            c.execute("SELECT type, title, desc, criteria, strictness, time_limit FROM exams_v3 WHERE code=?", (access_code,))
            res = c.fetchone()
            if res:
                db_type = res[0]
                selected_type = "Quick" if student_mode == "Стандартный экзамен" else ("MYP" if student_mode == "Экзамен MYP" else "Custom")
                
                if db_type != selected_type:
                    st.error(f"Ошибка доступа! Этот код предназначен для режима '{db_type}'. Переключите режим сверху.")
                else:
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
        st.markdown("## Кабинет учителя")
        st.markdown(f"👋 Добро пожаловать, **{teacher_username}**")
        menu_selection = st.radio("Навигация:", ["Дашборд", "Быстрые задачи", "MYP задачи", "Кастомные задачи", "Результаты"])
        st.markdown("---")
        if st.button("Выйти", type="primary"):
            st.session_state.role = None
            st.session_state.teacher_id = None
            st.session_state.teacher_username = None
            st.query_params.clear()
            st.rerun()

    if menu_selection == "Дашборд":
        st.header("Профиль и статистика")
        stats, total_submissions = get_teacher_stats(teacher_id)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Quick задач", stats.get("Quick", 0))
        c2.metric("MYP задач", stats.get("MYP", 0))
        c3.metric("Custom задач", stats.get("Custom", 0))
        c4.metric("Сданных работ", total_submissions)
        st.info("Здесь отображаются только ваши экзамены и связанные результаты.")
        st.markdown("### Мои экзамены")
        all_teacher_exams = get_teacher_exams(teacher_id)
        if not all_teacher_exams:
            st.caption("Пока нет опубликованных задач.")
        for exam_code, exam_title, exam_type, exam_time in all_teacher_exams:
            st.markdown(f"- **{exam_title}** (`{exam_type}`) — код: `{exam_code}`, время: {exam_time} мин.")

    elif menu_selection == "Быстрые задачи":
        st.header("Быстрые задачи (Базовый вариант)")
        with st.form("quick_exam"):
            nt = st.text_input("Название экзамена")
            nd = st.text_area("Описание задачи (Поддерживает HTML)")
            
            t_limit = st.number_input("Время на выполнение (минуты)", min_value=0, max_value=300, value=45, help="0 = без ограничений")
            
            col_c1, col_c2 = st.columns([3, 1])
            with col_c1:
                nc = st.text_input("Код доступа", value=st.session_state.gen_code)
            with col_c2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.form_submit_button("Сгенерировать код", type="secondary"):
                    st.session_state.gen_code = generate_random_code("FAST")
                    st.rerun()
                    
            ncr = st.text_area("Критерии оценивания (Текст)")
            
            if st.form_submit_button("Сохранить задачу", type="primary"):
                if nc and nt:
                    saved, save_message = save_teacher_exam(nc, "Quick", nt, nd, ncr, 5.0, t_limit, teacher_id)
                    if saved:
                        st.success(f"Задача сохранена! Код: {nc}")
                    else:
                        st.error(save_message)
                else:
                    st.warning("Укажите название и код доступа.")

    elif menu_selection == "MYP задачи":
        st.header("MYP задачи (Продвинутый уровень)")
        
        nt = st.text_input("Название MYP Задачи")
        
        col_c1, col_c2 = st.columns([3, 1])
        with col_c1:
            nc = st.text_input("Код доступа MYP", value=st.session_state.gen_code)
        with col_c2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Сгенерировать MYP-код", type="secondary"):
                st.session_state.gen_code = generate_random_code("MYP")
                st.rerun()

        st.markdown("### 1. Условие задачи и Предмет")
        myp_subject = st.selectbox("Специфика предмета MYP", [
            "Не указано", "Науки (Sciences)", "Математика (Mathematics)", 
            "Язык и литература", "Приобретение языка", "Индивидуумы и общества", 
            "Дизайн (Design)", "Искусство (Arts)", "Физкультура и здоровье (PHE)"
        ])
        
        task_file = st.file_uploader("Загрузить файл с условием (.docx или .txt)", type=["docx", "txt"])
        task_questions = st.text_area("Дополнительные вопросы (каждый с новой строки)", height=150)
        
        st.markdown("### 2. Дополнительные критерии (опционально)")
        crit_file = st.file_uploader("Загрузить рубрику (.docx, .txt)", type=["docx", "txt"])
        
        st.markdown("### 3. Настройки экзамена")
        t_limit = st.number_input("Время на выполнение (минуты)", min_value=0, max_value=300, value=60, help="0 = без ограничений")
        strictness = st.slider("Уровень строгости оценивания", min_value=1, max_value=10, value=5)

        if st.button("Опубликовать MYP задачу", type="primary"):
            if nt and nc:
                desc_content = read_file(task_file)
                questions_html = f"<br><h3>Дополнительные вопросы:</h3><p>{task_questions.replace(chr(10), '<br>')}</p>" if task_questions.strip() else ""
                final_desc = desc_content + questions_html
                
                subject_prefix = f"[ОФИЦИАЛЬНЫЙ ПРЕДМЕТ MYP: {myp_subject}]\n\n" if "Не указано" not in myp_subject else ""
                final_crit = subject_prefix + read_file(crit_file)
                
                if not final_desc.strip(): final_desc = "Смотрите вопросы."
                if not final_crit.strip(): final_crit = "Оценивать по стандартам MYP."

                saved, save_message = save_teacher_exam(nc, "MYP", nt, final_desc, final_crit, float(strictness), t_limit, teacher_id)
                if saved:
                    st.success(f"MYP Экзамен опубликован! Код доступа: {nc}")
                else:
                    st.error(save_message)
            else:
                st.warning("Пожалуйста, введите название и сгенерируйте код.")

    elif menu_selection == "Кастомные задачи":
        st.header("Кастомные задачи")
        with st.form("custom_exam"):
            c_title = st.text_input("Название кастомной задачи")
            c_desc = st.text_area("Описание задачи")
            c_file = st.file_uploader("Файл с условием (.docx/.txt)", type=["docx", "txt"])
            c_crit = st.text_area("Критерии оценивания")
            c_crit_file = st.file_uploader("Файл с критериями (.docx/.txt)", type=["docx", "txt"])
            c_time = st.number_input("Время на выполнение (минуты)", min_value=0, max_value=300, value=45, help="0 = без ограничений")
            c_strict = st.slider("Уровень строгости", min_value=1, max_value=10, value=5)
            c_code = st.text_input("Код доступа", value=st.session_state.gen_code)
            if st.form_submit_button("Сгенерировать код", type="secondary"):
                st.session_state.gen_code = generate_random_code("CSTM")
                st.rerun()
            publish_custom = st.form_submit_button("Сохранить кастомную задачу", type="primary")

            if publish_custom:
                if c_title and c_code:
                    file_desc = read_file(c_file)
                    file_crit = read_file(c_crit_file)
                    desc_parts = [part for part in [c_desc.strip(), file_desc.strip()] if part]
                    crit_parts = [part for part in [c_crit.strip(), file_crit.strip()] if part]
                    final_desc = "<br>".join(desc_parts)
                    final_crit = "\n".join(crit_parts)
                    if not final_desc:
                        final_desc = "Описание не указано."
                    if not final_crit:
                        final_crit = "Оценить по содержательности, структуре и аргументации."

                    saved, save_message = save_teacher_exam(c_code, "Custom", c_title, final_desc, final_crit, float(c_strict), c_time, teacher_id)
                    if saved:
                        st.success(f"Кастомная задача сохранена! Код: {c_code}")
                    else:
                        st.error(save_message)
                else:
                    st.warning("Укажите название и код доступа.")

        st.markdown("### Мои кастомные задачи")
        custom_exams = get_teacher_exams(teacher_id, "Custom")
        if not custom_exams:
            st.info("У вас пока нет кастомных задач.")
        for exam_code, exam_title, exam_type, exam_time in custom_exams:
            with st.expander(f"{exam_title} ({exam_code})"):
                st.write(f"Тип: {exam_type} | Лимит: {exam_time} мин.")
                if st.button(f"Удалить {exam_code}", type="secondary", key=f"del-{exam_code}"):
                    c = db_conn.cursor()
                    c.execute("DELETE FROM exams_v3 WHERE code=? AND teacher_id=?", (exam_code, teacher_id))
                    db_conn.commit()
                    st.success(f"Задача {exam_code} удалена.")
                    st.rerun()

    elif menu_selection == "Результаты":
        st.header("Результаты студентов")
        c = db_conn.cursor()
        c.execute("SELECT title FROM exams_v3 WHERE teacher_id=?", (teacher_id,))
        teacher_titles = [row[0] for row in c.fetchall()]
        if teacher_titles:
            placeholders = ",".join(["?"] * len(teacher_titles))
            c.execute(f"SELECT name, title, essay, grade FROM submissions WHERE title IN ({placeholders})", teacher_titles)
            data = c.fetchall()
        else:
            data = []
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
