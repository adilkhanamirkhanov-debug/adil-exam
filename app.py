import streamlit as st
from openai import OpenAI
import sqlite3

# --- ПОДКЛЮЧЕНИЕ ВНЕШНЕГО ДИЗАЙНА CSS ---
def load_css(file_name):
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except Exception as e:
        pass # Если файла нет, просто игнорируем

load_css("style.css")
# -----------------------------------------

# --- НАСТРОЙКИ СТРАНИЦЫ И ТЕМЫ ---
# Убрали эмодзи из page_icon
st.set_page_config(page_title="AI Экзаменатор", layout="wide", initial_sidebar_state="expanded")

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ (SQLite) ---
def init_db():
    conn = sqlite3.connect('platform.db')
    c = conn.cursor()
    # Таблица пользователей (учителей)
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, role TEXT)''')
    # Таблица экзаменов
    c.execute('''CREATE TABLE IF NOT EXISTS exams 
                 (code TEXT PRIMARY KEY, title TEXT, desc TEXT, criteria TEXT)''')
    # Таблица результатов
    c.execute('''CREATE TABLE IF NOT EXISTS submissions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, title TEXT, essay TEXT, grade TEXT)''')
    
    # Создаем стандартного учителя, если его нет в базе
    c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES ('admin', '12345', 'Teacher')")
    
    conn.commit()
    conn.close()

init_db()

# Функции для работы с БД
def verify_user(username, password):
    conn = sqlite3.connect('platform.db')
    c = conn.cursor()
    c.execute("SELECT role FROM users WHERE username=? AND password=?", (username, password))
    res = c.fetchone()
    conn.close()
    return res[0] if res else None

def add_exam(code, title, desc, criteria):
    conn = sqlite3.connect('platform.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO exams (code, title, desc, criteria) VALUES (?, ?, ?, ?)", (code, title, desc, criteria))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False # Такой код доступа уже существует
    conn.close()
    return success

def get_exam_by_code(code):
    conn = sqlite3.connect('platform.db')
    c = conn.cursor()
    c.execute("SELECT title, desc, criteria, code FROM exams WHERE code=?", (code,))
    res = c.fetchone()
    conn.close()
    if res:
        return {"title": res[0], "desc": res[1], "criteria": res[2], "code": res[3]}
    return None

def add_submission(name, title, essay, grade):
    conn = sqlite3.connect('platform.db')
    c = conn.cursor()
    c.execute("INSERT INTO submissions (name, title, essay, grade) VALUES (?, ?, ?, ?)", (name, title, essay, grade))
    conn.commit()
    conn.close()

def get_submissions():
    conn = sqlite3.connect('platform.db')
    c = conn.cursor()
    c.execute("SELECT name, title, essay, grade FROM submissions")
    rows = c.fetchall()
    conn.close()
    return [{"name": r[0], "title": r[1], "essay": r[2], "grade": r[3]} for r in rows]

# --- НАСТРОЙКА API ---
API_KEY = st.secrets["API_KEY"]
MODEL_NAME = "openai/gpt-4o-mini" 

@st.cache_resource
def get_ai_client():
    # Очистка ключа от невидимых символов
    clean_key = API_KEY.encode('ascii', 'ignore').decode('ascii').strip()
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=clean_key,
    )

client = get_ai_client()

# --- СЛОВАРЬ ПЕРЕВОДОВ (БЕЗ ЭМОДЗИ) ---
LANGUAGES = {
    'ru': {
        'welcome_title': "Добро пожаловать на платформу AI Экзаменатор",
        'role_select_text': "Пожалуйста, выберите вашу роль для входа:",
        'teacher_login_btn': "Войти как Учитель",
        'student_login_btn': "Войти как Студент",
        'teacher_login_header': "Вход для учителя",
        'student_login_header': "Вход для студента",
        'login_label': "Логин",
        'pass_label': "Пароль",
        'admin_check_err': "Неверный логин или пароль",
        'code_entry_label': "Код доступа к экзамену",
        'exam_not_found_err': "Экзамен с таким кодом не найден",
        'sidebar_teacher_title': "Кабинет Учителя",
        'sidebar_student_title': "Кабинет Студента",
        'logout_btn': "Выйти",
        'tabs_create_assignment': "Создать задание",
        'tabs_graded_works': "Проверенные работы",
        'create_assignment_header': "Добавление нового экзамена/задания",
        'new_title_label': "Название:",
        'new_desc_label': "Описание и суть:",
        'new_code_label': "Код доступа для студентов:",
        'generate_criteria_btn': "Создать критерии через ИИ",
        'new_criteria_label': "Критерии успеха (по 100-балльной шкале):",
        'gen_crit_desc_warning': "Сначала напишите описание задания!",
        'generated_crit_info': "Сгенерированные критерии (скопируйте их выше):",
        'save_assignment_btn': "Сохранить задание",
        'fields_empty_err': "Заполните все поля, включая критерии и код!",
        'code_exists_err': "Экзамен с таким кодом уже существует! Придумайте другой.",
        'graded_works_header': "Проверенные работы студентов",
        'student_name_label': "ФИО Студента",
        'graded_work_info_title': "Работа: {student} | {exam} | Оценка: {grade}/100",
        'student_essay_section': "Текст студента:",
        'ai_result_section': "Результат ИИ:",
        'student_exam_welcome': "Экзамен: {exam_title}",
        'exam_description': "Описание: {desc}",
        'exam_criteria': "Критерии оценки:\n{criteria}",
        'submit_work_btn': "Сдать работу",
        'submission_spinner': "Проверка...",
        'submission_success': "Успешно сдано!",
        'submission_warning': "Заполните все поля (ФИО и ответ)!",
        'grading_header': "Оценка за экзамен: {grade} / 100",
        'task_label': "Задание",
    },
    'kk': {
        'welcome_title': "AI Экзаменатор платформасына қош келдіңіз",
        'role_select_text': "Кіру үшін рөліңізді таңдаңыз:",
        'teacher_login_btn': "Мұғалім ретінде кіру",
        'student_login_btn': "Студент ретінде кіру",
        'teacher_login_header': "Мұғалім кіруі",
        'student_login_header': "Студент кіруі",
        'login_label': "Логин",
        'pass_label': "Құпия сөз",
        'admin_check_err': "Логин немесе құпия сөз қате",
        'code_entry_label': "Емтиханға кіру коды",
        'exam_not_found_err': "Бұл кодпен емтихан табылмады",
        'sidebar_teacher_title': "Мұғалім кабинеті",
        'sidebar_student_title': "Студент кабинеті",
        'logout_btn': "Шығу",
        'tabs_create_assignment': "Тапсырма жасау",
        'tabs_graded_works': "Тексерілген жұмыстар",
        'create_assignment_header': "Жаңа емтихан/тапсырма қосу",
        'new_title_label': "Атауы:",
        'new_desc_label': "Сипаттамасы және мәні:",
        'new_code_label': "Студенттерге арналған кіру коды:",
        'generate_criteria_btn': "ЖИ арқылы критерий жасау",
        'new_criteria_label': "Сәттілік критерийлері (100-балдық шкала):",
        'gen_crit_desc_warning': "Алдымен тапсырма сипаттамасын жазыңыз!",
        'generated_crit_info': "Генерацияланған критерийлер (жоғарыға көшіріңіз):",
        'save_assignment_btn': "Тапсырманы сақтау",
        'fields_empty_err': "Барлық өрістерді толтырыңыз!",
        'code_exists_err': "Мұндай код бар! Басқасын ойлап табыңыз.",
        'graded_works_header': "Студенттердің тексерілген жұмыстары",
        'student_name_label': "Студенттің аты-жөні",
        'graded_work_info_title': "Жұмыс: {student} | {exam} | Бағасы: {grade}/100",
        'student_essay_section': "Студент мәтіні:",
        'ai_result_section': "ЖИ нәтижесі:",
        'student_exam_welcome': "Емтихан: {exam_title}",
        'exam_description': "Сипаттамасы: {desc}",
        'exam_criteria': "Бағалау критерийлері:\n{criteria}",
        'submit_work_btn': "Жұмысты тапсыру",
        'submission_spinner': "Тексерілуде...",
        'submission_success': "Тапсырылды!",
        'submission_warning': "Барлық өрістерді толтырыңыз (Аты-жөні және жауап)!",
        'grading_header': "Емтихан бағасы: {grade} / 100",
        'task_label': "Тапсырма",
    },
    'en': {
        'welcome_title': "Welcome to AI Examiner Platform",
        'role_select_text': "Please select your role to log in:",
        'teacher_login_btn': "Log in as Teacher",
        'student_login_btn': "Log in as Student",
        'teacher_login_header': "Teacher Log in",
        'student_login_header': "Student Log in",
        'login_label': "Login",
        'pass_label': "Password",
        'admin_check_err': "Incorrect login or password",
        'code_entry_label': "Exam Access Code",
        'exam_not_found_err': "Exam with this code not found",
        'sidebar_teacher_title': "Teacher Cabinet",
        'sidebar_student_title': "Student Cabinet",
        'logout_btn': "Log out",
        'tabs_create_assignment': "Create Assignment",
        'tabs_graded_works': "Graded Works",
        'create_assignment_header': "Add New Exam/Assignment",
        'new_title_label': "Title:",
        'new_desc_label': "Description and Essence:",
        'new_code_label': "Access Code for Students:",
        'generate_criteria_btn': "Generate Criteria via AI",
        'new_criteria_label': "Success Criteria (100-point scale):",
        'gen_crit_desc_warning': "Write assignment description first!",
        'generated_crit_info': "Generated criteria (copy them above):",
        'save_assignment_btn': "Save Assignment",
        'fields_empty_err': "Fill all fields, including criteria and code!",
        'code_exists_err': "Exam with this code already exists!",
        'graded_works_header': "Graded Student Works",
        'student_name_label': "Student's Full Name",
        'graded_work_info_title': "Work: {student} | {exam} | Grade: {grade}/100",
        'student_essay_section': "Student's Text:",
        'ai_result_section': "AI Result:",
        'student_exam_welcome': "Exam: {exam_title}",
        'exam_description': "Description: {desc}",
        'exam_criteria': "Grading Criteria:\n{criteria}",
        'submit_work_btn': "Submit Work",
        'submission_spinner': "Grading...",
        'submission_success': "Submitted!",
        'submission_warning': "Fill all fields (Name and answer)!",
        'grading_header': "Exam Grade: {grade} / 100",
        'task_label': "Task",
    }
}

# --- CUSTOM CSS ---
st.markdown("""
<style>
    .stButton > button {
        border-radius: 6px;
        border: none;
        padding: 0.6rem 1.2rem;
        transition: all 0.2s ease-in-out;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        text-transform: uppercase;
        font-weight: 600;
        letter-spacing: 0.5px;
    }
    .stButton > button[kind="primary"] {
        background-color: #0056b3;
        color: white;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #004494;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.15);
    }
    div[data-testid="stExpander"] {
        border-radius: 6px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }
</style>
""", unsafe_allow_html=True)

# --- СОСТОЯНИЕ СЕССИИ ---
if "role" not in st.session_state:
    st.session_state.role = None
if "current_exam" not in st.session_state:
    st.session_state.current_exam = None
if "lang" not in st.session_state:
    st.session_state.lang = 'ru'

# --- ПЕРЕКЛЮЧАТЕЛЬ ЯЗЫКА ---
lang_codes = ['ru', 'kk', 'en']
lang_names = {'ru': 'Русский', 'kk': 'Қазақша', 'en': 'English'}

def on_lang_change():
    st.session_state.lang = st.session_state.selected_lang_full

st.sidebar.markdown("---")
st.sidebar.selectbox(
    "Язык / Language / Тіл:",
    options=lang_codes,
    format_func=lambda x: lang_names[x],
    key="selected_lang_full",
    index=lang_codes.index(st.session_state.lang),
    on_change=on_lang_change
)
st.sidebar.markdown("---")

L = LANGUAGES[st.session_state.lang]

# --- ФУНКЦИИ ИИ ---
def generate_criteria(task_description):
    prompt = f"Ты опытный методист. Напиши четкие критерии оценки (рубрикатор) для задания: '{task_description}'. Оценивание идет по 100-балльной шкале. Напиши кратко, списком."
    response = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0.7)
    return response.choices[0].message.content

def grade_essay(task_title, task_desc, criteria, essay):
    prompt = f"Ты строгий, но справедливый экзаменатор.\nТема: {task_title}\nОписание: {task_desc}\nКритерии оценивания: {criteria}\nЭссе студента: {essay}\nОцени работу строго по заданным критериям.\nФормат ответа:\n### Итоговый балл: [Балл] / 100\n### Отзыв:\n[Твой подробный фидбек по каждому критерию]"
    response = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0.2)
    return response.choices[0].message.content

# --- ГЛАВНОЕ МЕНЮ (Стартовый экран) ---
if st.session_state.role is None:
    
    # 1. БОКОВОЕ МЕНЮ (Описание и вход для учителя)
    with st.sidebar:
        st.markdown("### 🧠 О платформе")
        st.info(
            "AI Exam Platform — это инновационная система проверки знаний. "
            "Искусственный интеллект автоматически анализирует эссе, оценивает их "
            "по заданным критериям и предоставляет развернутый фидбек."
        )
        
        st.markdown("---")
        
        st.markdown("### 👨‍🏫 Вход для преподавателя")
        # Поля для ввода логина и пароля
        teacher_username = st.text_input("Логин", key="t_login")
        teacher_password = st.text_input("Пароль", type="password", key="t_pass")
        
        if st.button("Войти в панель управления", use_container_width=True):
            if teacher_username == "admin" and teacher_password == "12345": # Замените на вашу функцию проверки (например: if authenticate(teacher_username, teacher_password): )
                st.session_state.role = "Teacher"
                st.rerun()
            else:
                st.error("❌ Неверный логин или пароль")


    # 2. ГЛАВНАЯ СТРАНИЦА (Только для студента)
    # Делаем пустые колонки по бокам, чтобы логотип был ровно по центру и нужного размера
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        try:
            # use_container_width делает картинку большой и адаптивной
            st.image("logo.png", use_container_width=True) 
        except:
            pass
            
    st.markdown("<h1 style='text-align: center;'>Сдача экзамена</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #bbaadd !important;'>Введите код доступа, выданный преподавателем</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True) # Небольшой отступ
    
    # Снова используем колонки, чтобы поле для ввода кода не было слишком растянутым
    col_space1, col_input, col_space3 = st.columns([1, 2, 1])
    with col_input:
        access_code = st.text_input("Код доступа:", placeholder="Например: EXAM-123", label_visibility="collapsed")
        
        if st.button("🚀 Начать экзамен", type="primary", use_container_width=True):
            # Замените get_exam_by_code на вашу реальную функцию поиска экзамена в БД
            exam = get_exam_by_code(access_code) 
            if exam:
                st.session_state.role = "Student"
                st.session_state.current_exam = exam
                st.rerun()
            else:
                st.error("⚠️ Экзамен с таким кодом не найден. Проверьте правильность кода.")

# --- ЛИЧНЫЙ КАБИНЕТ УЧИТЕЛЯ ---
elif st.session_state.role == "Teacher":
    col_head1, col_head2 = st.columns([1, 3])
    with col_head1:
        try:
            st.image("Ai.png", width=100)
        except:
            pass
    with col_head2:
        st.sidebar.title(L['sidebar_teacher_title'])

    if st.sidebar.button(L['logout_btn']):
        st.session_state.role = None
        st.rerun()
        
    tab1, tab2 = st.tabs([L['tabs_create_assignment'], L['tabs_graded_works']])
    
    with tab1:
        st.header(L['create_assignment_header'])
        new_title = st.text_input(L['new_title_label'])
        new_desc = st.text_area(L['new_desc_label'], height=150)
        new_code = st.text_input(L['new_code_label'])
        
        st.markdown(f"**{L['new_criteria_label']}**")
        col_crit1, col_crit2 = st.columns([3, 1])
        with col_crit1:
            new_criteria = st.text_area(L['task_label'], height=200, placeholder=L['generated_crit_info'])
        with col_crit2:
            if st.button(L['generate_criteria_btn'], use_container_width=True):
                if new_desc:
                    st.session_state.gen_crit = generate_criteria(new_desc)
                    st.rerun()
        
        if "gen_crit" in st.session_state:
            with st.expander(L['generated_crit_info'], expanded=True):
                st.info(st.session_state.gen_crit)

        if st.button(L['save_assignment_btn'], type="primary", use_container_width=True):
            if new_title and new_desc and new_criteria and new_code:
                success = add_exam(new_code, new_title, new_desc, new_criteria)
                if success:
                    st.success(f"Сохранено! Код для студентов: {new_code}")
                    if "gen_crit" in st.session_state:
                        del st.session_state.gen_crit
                else:
                    st.error(L['code_exists_err'])
            else:
                st.error(L['fields_empty_err'])

    with tab2:
        st.header(L['graded_works_header'])
        submissions = get_submissions()
        if not submissions:
            st.info("Пока никто не сдал.")
        else:
            for sub in reversed(submissions):
                grade_val = "0"
                try:
                    parts = sub['grade'].split(' / 100')
                    grade_val = parts[0].split(': ')[-1]
                except:
                    pass
                
                exp_title = L['graded_work_info_title'].format(student=sub['name'], exam=sub['title'], grade=grade_val)
                with st.expander(exp_title):
                    st.markdown(f"**{L['student_essay_section']}**\n\n{sub['essay']}")
                    st.markdown("---")
                    st.markdown(f"**{L['ai_result_section']}**\n\n{sub['grade']}")

# --- ЛИЧНЫЙ КАБИНЕТ СТУДЕНТА ---
elif st.session_state.role == "Student":
    
    # Жестко скрываем боковое меню и шапку сайта (Режим киоска)
    st.markdown("""
        <style>
            [data-testid="stSidebar"] {display: none !important; width: 0 !important;}
            section[data-testid="stSidebar"] {display: none !important;}
            [data-testid="collapsedControl"] {display: none !important;}
            header {display: none !important; visibility: hidden !important;}
            #MainMenu {visibility: hidden !important;}
            footer {visibility: hidden !important;}
            .block-container {padding-top: 1rem !important;}
        </style>
    """, unsafe_allow_html=True)

    col_head1_s, col_head2_s = st.columns([1, 3])
    with col_head1_s:
        try:
            st.image("Ai.png", width=100)
        except:
            pass
    with col_head2_s:
        st.title(L['sidebar_student_title'])

    exam = st.session_state.current_exam
    st.header(L['student_exam_welcome'].format(exam_title=exam['title']))
    
    with st.expander(L['task_label'], expanded=True):
        st.markdown(L['exam_description'].format(desc=exam['desc']))
        st.markdown(L['exam_criteria'].format(criteria=exam['criteria']))
        
    st.markdown("---")
    
    # Инициализация состояния сдачи работы для студента
    if "student_submitted" not in st.session_state:
        st.session_state.student_submitted = False
        st.session_state.student_result = ""
        st.session_state.student_name_saved = ""

    # Если студент ЕЩЕ НЕ сдал работу — показываем поля ввода
    if not st.session_state.student_submitted:
        student_name = st.text_input(L['student_name_label'])
        essay_text = st.text_area(L['task_label'], height=300)
        
        st.markdown("---")
        
        if st.button(L['submit_work_btn'], type="primary", use_container_width=True):
            if student_name and essay_text:
                with st.spinner(L['submission_spinner']):
                    result = grade_essay(exam['title'], exam['desc'], exam['criteria'], essay_text)
                    
                    # Сохраняем в базу данных навсегда
                    add_submission(student_name, exam['title'], essay_text, result)
                    
                    # Сохраняем результаты в сессию, чтобы они не пропали
                    st.session_state.student_result = result
                    st.session_state.student_name_saved = student_name
                    st.session_state.student_submitted = True
                    st.rerun() # Перезагружаем страницу, чтобы показать результаты
            else:
                st.warning(L['submission_warning'])

    # Если студент УЖЕ сдал работу — показываем результат и кнопки выхода/скачивания
    else:
        st.success(L['submission_success'])
        
        with st.expander("Ваш результат и отзыв ИИ", expanded=True):
            st.markdown(st.session_state.student_result)
            
        st.markdown("---")
        col_btn1, col_btn2 = st.columns(2)
        
        # Кнопка 1: Скачать результат в TXT
        with col_btn1:
            # Формируем текст для скачивания
            feedback_file_content = f"Студент: {st.session_state.student_name_saved}\nЭкзамен: {exam['title']}\n\n=== РЕЗУЛЬТАТ И ОТЗЫВ ИИ ===\n{st.session_state.student_result}"
            
            st.download_button(
                label="📥 Скачать Feedback (TXT)",
                data=feedback_file_content,
                file_name=f"Result_{st.session_state.student_name_saved}.txt",
                mime="text/plain",
                use_container_width=True
            )
            
        # Кнопка 2: Выход в главное меню
        with col_btn2:
            if st.button("🚪 Выйти в главное меню", use_container_width=True):
                # Очищаем сессию и возвращаем на стартовый экран
                st.session_state.student_submitted = False
                st.session_state.student_result = ""
                st.session_state.student_name_saved = ""
                st.session_state.role = None
                st.session_state.current_exam = None
                st.rerun()
