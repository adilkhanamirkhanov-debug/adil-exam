import streamlit as st
import sqlite3
import pandas as pd
from openai import OpenAI
import random
import string

# --- 1. CONFIG ---
st.set_page_config(
    page_title="AdilExam", 
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

# --- 3. SIDEBAR FIX ---
if "role" not in st.session_state: st.session_state.role = None
if "gen_code" not in st.session_state: st.session_state.gen_code = ""

if st.session_state.role != "Student":
    st.markdown("""<style>[data-testid="collapsedControl"] {display: flex !important; top: 25px !important;} section[data-testid="stSidebar"] {display: flex !important;}</style>""", unsafe_allow_html=True)
else:
    st.markdown("""<style>[data-testid="collapsedControl"], section[data-testid="stSidebar"] {display: none !important;}</style>""", unsafe_allow_html=True)

# --- 4. DATABASE ---
def init_db():
    conn = sqlite3.connect('platform.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS exams_v2 (code TEXT PRIMARY KEY, type TEXT, title TEXT, desc TEXT, criteria TEXT, strictness REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, title TEXT, essay TEXT, grade TEXT)')
    conn.commit()
    return conn

db_conn = init_db()

# ГЕНЕРАТОР КОДА
def generate_random_code(prefix="EXAM"):
    chars = string.ascii_uppercase + string.digits
    return f"{prefix}-" + "".join(random.choices(chars, k=5))

# ЧТЕНИЕ ФАЙЛОВ
def read_file(uploaded_file):
    if uploaded_file is not None:
        try:
            return uploaded_file.getvalue().decode("utf-8")
        except:
            return "Ошибка чтения файла. Пожалуйста, используйте текстовые форматы (.txt)."
    return ""

# --- 5. AI LOGIC ---
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=st.secrets["API_KEY"].strip(),
)

def grade_essay(title, desc, criteria, strictness, essay):
    strictness_guide = "Be balanced and fair."
    if strictness > 7:
        strictness_guide = "Grade VERY strictly. Deduct points for any minor logical, grammatical, or structural mistakes. Be a tough grader."
    elif strictness < 4:
        strictness_guide = "Grade leniently and encouragingly. Focus on the main ideas and forgive minor mistakes."

    prompt = f"""
    Grade this response for the exam: '{title}'.
    Task/Context: {desc}
    Grading Criteria: {criteria}
    Strictness Level (1-10): {strictness}. {strictness_guide}
    
    CRITICAL INSTRUCTION: You MUST write your 'Feedback' in the EXACT SAME LANGUAGE that the student used in their 'Student's Work'. If the student wrote in Russian, reply in Russian. If Kazakh, reply in Kazakh. If English, reply in English.
    
    Student's Work: 
    {essay}
    
    Format: 
    ### Grade: [X]/100
    ### Feedback: [Detailed text in the student's language]
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
        st.markdown("### Teacher Login")
        t_user = st.text_input("Username")
        t_pass = st.text_input("Password", type="password")
        if st.button("Login", type="primary"):
            if t_user == "admin" and t_pass == "12345":
                st.session_state.role = "Teacher"
                st.rerun()

    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown('<p class="logo-text">AdilExam</p>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<p style='text-align: center; opacity: 0.7;'>Enter access code to start</p>", unsafe_allow_html=True)
        access_code = st.text_input("Code", placeholder="EXAM-CODE", label_visibility="collapsed")
        if st.button("Start Exam", type="primary"):
            c = db_conn.cursor()
            c.execute("SELECT type, title, desc, criteria, strictness FROM exams_v2 WHERE code=?", (access_code,))
            res = c.fetchone()
            if res:
                st.session_state.current_exam = {
                    "type": res[0], "title": res[1], "desc": res[2], 
                    "criteria": res[3], "strictness": res[4]
                }
                st.session_state.role = "Student"
                st.rerun()
            else:
                st.error("Code not found or invalid.")

# ПАНЕЛЬ УЧИТЕЛЯ (КАБИНЕТ)
elif st.session_state.role == "Teacher":
    with st.sidebar:
        st.markdown("## Меню учителя")
        menu_selection = st.radio("Навигация:", ["Быстрые задачи", "MYP задачи", "Кастомные задачи", "Результаты"])
        st.markdown("---")
        if st.button("Выйти", type="primary"):
            st.session_state.role = None
            st.rerun()

    if menu_selection == "Быстрые задачи":
        st.header("Быстрые задачи ")
        with st.form("quick_exam"):
            nt = st.text_input("Название экзамена")
            nd = st.text_area("Описание задачи")
            
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
                    c = db_conn.cursor()
                    c.execute("INSERT OR REPLACE INTO exams_v2 VALUES (?,?,?,?,?,?)", (nc, "Quick", nt, nd, ncr, 5.0))
                    db_conn.commit()
                    st.success(f"Задача сохранена! Код: {nc}")
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
            if st.button("Сгенерировать MYP-код"):
                st.session_state.gen_code = generate_random_code("MYP")
                st.rerun()

        st.markdown("### 1. Условие задачи")
        task_file = st.file_uploader("Загрузить файл с условием (.docx)", type=["docx"])
        task_questions = st.text_area("Дополнительные вопросы (каждый с новой строки)", height=150)
        
        st.markdown("### 2. Критерии оценивания")
        crit_file = st.file_uploader("Загрузить рубрику/критерии (.docx)", type=["docx"])
        
        st.markdown("### 3. Настройки ИИ")
        strictness = st.slider("Уровень строгости оценивания", min_value=1, max_value=10, value=5, help="1 = Мягко, 10 = Очень строго")

        if st.button("Опубликовать MYP задачу", type="primary"):
            if nt and nc:
                final_desc = read_file(task_file) + "\n\nВопросы:\n" + task_questions
                final_crit = read_file(crit_file)
                
                if not final_desc.strip(): final_desc = "Смотрите вопросы."
                if not final_crit.strip(): final_crit = "Оценивать по стандартам MYP."

                c = db_conn.cursor()
                c.execute("INSERT OR REPLACE INTO exams_v2 VALUES (?,?,?,?,?,?)", (nc, "MYP", nt, final_desc, final_crit, float(strictness)))
                db_conn.commit()
                st.success(f"MYP Экзамен опубликован! Код доступа: {nc}")
            else:
                st.warning("Пожалуйста, введите название и сгенерируйте код.")

    elif menu_selection == "Кастомные задачи":
        st.header("Кастомные задачи")
        st.info("Этот раздел находится в разработке. Здесь будет конструктор нестандартных экзаменов.")

    elif menu_selection == "Результаты":
        st.header("Результаты студентов")
        c = db_conn.cursor()
        c.execute("SELECT name, title, essay, grade FROM submissions")
        data = c.fetchall()
        if data:
            df = pd.DataFrame(data, columns=["Имя", "Экзамен", "Эссе", "Оценка"])
            st.download_button("Скачать CSV", df.to_csv(index=False).encode('utf-8-sig'), "results.csv", type="primary")
            for r in reversed(data):
                with st.expander(f"{r[0]} — {r[1]}"):
                    st.write(f"**Ответ:**\n{r[2]}")
                    st.info(f"**Оценка ИИ:**\n{r[3]}")
        else:
            st.info("Пока нет ни одной сданной работы.")

# СТУДЕНТ
elif st.session_state.role == "Student":
    exam = st.session_state.current_exam
    st.markdown(f'<p class="logo-text" style="font-size: 32px !important;">{exam["title"]}</p>', unsafe_allow_html=True)
    
    with st.expander("Показать условие задачи", expanded=True):
        st.write(exam['desc'])
        
    s_name = st.text_input("Ваше полное имя")
    s_essay = st.text_area("Ваш ответ / Эссе", height=350)
    
    col_bt1, col_bt2 = st.columns(2)
    with col_bt1:
        if st.button("Отправить работу", type="primary"):
            if s_name and s_essay:
                with st.spinner("AI анализирует ваш ответ..."):
                    grade = grade_essay(exam['title'], exam['desc'], exam['criteria'], exam['strictness'], s_essay)
                    c = db_conn.cursor()
                    c.execute("INSERT INTO submissions (name, title, essay, grade) VALUES (?,?,?,?)", (s_name, exam['title'], s_essay, grade))
                    db_conn.commit()
                    st.success("Работа успешно сдана!")
                    st.markdown(grade)
            else: 
                st.warning("Пожалуйста, заполните имя и напишите ответ.")
    with col_bt2:
        if st.button("Выйти на главную", type="secondary"):
            st.session_state.role = None
            st.rerun()
