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



# --- СОСТОЯНИЕ СЕССИИ ---
if "role" not in st.session_state:
    st.session_state.role = None
if "current_exam" not in st.session_state:
    st.session_state.current_exam = None
if "lang" not in st.session_state:
    st.session_state.lang = 'ru'




# --- ФУНКЦИИ ИИ ---
def generate_criteria(task_description):
    prompt = f"Ты опытный методист. Напиши четкие критерии оценки (рубрикатор) для задания: '{task_description}'. Оценивание идет по 100-балльной шкале. Напиши кратко, списком."
    response = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0.7)
    return response.choices[0].message.content

def grade_essay(task_title, task_desc, criteria, essay):
    prompt = f"Ты строгий, но справедливый экзаменатор.\nТема: {task_title}\nОписание: {task_desc}\nКритерии оценивания: {criteria}\nЭссе студента: {essay}\nОцени работу строго по заданным критериям.\nФормат ответа:\n### Итоговый балл: [Балл] / 100\n### Отзыв:\n[Твой подробный фидбек по каждому критерию]"
    response = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0.2)
    return response.choices[0].message.content

# --- MAIN MENU (Start Screen) ---
if st.session_state.role is None:
    
    # 1. SIDEBAR (About & Teacher Login)
    with st.sidebar:
        st.markdown("### About the Platform")
        st.info(
            "AI Exam Platform is an innovative knowledge assessment system. "
            "The AI automatically analyzes essays, evaluates them according to "
            "set criteria, and provides detailed feedback."
        )
        
        st.markdown("---")
        
        st.markdown("### Teacher Login")
        teacher_username = st.text_input("Username", key="t_login")
        teacher_password = st.text_input("Password", type="password", key="t_pass")
        
        if st.button("Login to Dashboard", use_container_width=True):
            # Check credentials (replace with your logic if needed)
            if teacher_username == "admin" and teacher_password == "12345":
                st.session_state.role = "Teacher"
                st.rerun()
            else:
                st.error("Invalid username or password")

    # 2. MAIN PAGE (Student Access)
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        try:
            st.image("Ai.png", use_container_width=True) 
        except:
            pass
            
    st.markdown("<h1 style='text-align: center;'>Take the Exam</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #bbaadd !important;'>Enter the access code provided by your teacher</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_space1, col_input, col_space3 = st.columns([1, 2, 1])
    with col_input:
        access_code = st.text_input("Access Code:", placeholder="E.g.: EXAM-123", label_visibility="collapsed")
        
        if st.button("Start Exam", type="primary", use_container_width=True):
            exam = get_exam_by_code(access_code) 
            if exam:
                st.session_state.role = "Student"
                st.session_state.current_exam = exam
                st.rerun()
            else:
                st.error("No exam found with this code.")
# --- TEACHER DASHBOARD ---
elif st.session_state.role == "Teacher":
    with st.sidebar:
        st.title("Teacher Panel")
        if st.button("Logout"):
            st.session_state.role = None
            st.rerun()

    tab1, tab2 = st.tabs(["Create Assignment", "Graded Works"])
    
    with tab1:
        st.header("Create New Assignment")
        new_title = st.text_input("Assignment Title")
        new_desc = st.text_area("Task Description (for AI and Students)", height=150)
        new_code = st.text_input("Access Code (e.g., EXAM-2024)")
        
        st.markdown("**Grading Criteria**")
        col_crit1, col_crit2 = st.columns([3, 1])
        with col_crit1:
            # If AI generated criteria, it will appear here
            default_crit = st.session_state.get("gen_crit", "")
            new_criteria = st.text_area("Criteria", value=default_crit, height=200, placeholder="Describe how AI should grade the work...")
        with col_crit2:
            if st.button("AI Generate Criteria", use_container_width=True):
                if new_desc:
                    with st.spinner("Generating..."):
                        st.session_state.gen_crit = generate_criteria(new_desc)
                        st.rerun()
                else:
                    st.warning("Please fill the description first!")
        
        if st.button("Save Assignment", type="primary", use_container_width=True):
            if new_title and new_desc and new_criteria and new_code:
                success = add_exam(new_code, new_title, new_desc, new_criteria)
                if success:
                    st.success(f"Saved! Student Access Code: {new_code}")
                    if "gen_crit" in st.session_state:
                        del st.session_state.gen_crit
                else:
                    st.error("This Access Code already exists!")
            else:
                st.error("Please fill all fields!")

    with tab2:
        st.header("Graded Submissions")
        submissions = get_submissions()
        if not submissions:
            st.info("No submissions yet.")
        else:
            # --- DOWNLOAD SECTION ---
            import pandas as pd
            import io

            # Convert database results to a DataFrame for easy export
            df = pd.DataFrame(submissions)
            
            # Create CSV buffer
            csv = df.to_csv(index=False).encode('utf-16')
            
            st.download_button(
                label="📥 Download All Results (CSV)",
                data=csv,
                file_name="exam_results.csv",
                mime="text/csv",
            )
            st.markdown("---")

            # Display individual cards
            for sub in reversed(submissions):
                grade_val = "N/A"
                try:
                    # Logic to extract numerical grade if possible
                    grade_val = sub['grade'].split('/')[0].strip()
                except:
                    pass
                
                exp_title = f"Student: {sub['name']} | Exam: {sub['title']} | Result: {grade_val}"
                with st.expander(exp_title):
                    st.markdown(f"**Student's Essay:**\n\n{sub['essay']}")
                    st.markdown("---")
                    st.markdown(f"**AI Feedback & Grade:**\n\n{sub['grade']}")

# --- STUDENT AREA ---
elif st.session_state.role == "Student":
    
    # Kiosk Mode: Hiding sidebar and header via CSS
    st.markdown("""
        <style>
            [data-testid="stSidebar"] {display: none !important; width: 0 !important;}
            section[data-testid="stSidebar"] 
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
        st.title("Examination Portal")

    exam = st.session_state.current_exam
    st.header(f"Exam: {exam['title']}")
    
    with st.expander("Task Instructions", expanded=True):
        st.markdown(f"**Description:**\n{exam['desc']}")
        st.markdown(f"**Grading Criteria:**\n{exam['criteria']}")
        
    st.markdown("---")
    
    if "student_submitted" not in st.session_state:
        st.session_state.student_submitted = False
        st.session_state.student_result = ""
        st.session_state.student_name_saved = ""

    if not st.session_state.student_submitted:
        student_name = st.text_input("Enter your Full Name")
        essay_text = st.text_area("Write your essay here", height=300)
        
        st.markdown("---")
        
        if st.button("Submit My Work", type="primary", use_container_width=True):
            if student_name and essay_text:
                with st.spinner("AI is evaluating your work... Please wait."):
                    result = grade_essay(exam['title'], exam['desc'], exam['criteria'], essay_text)
                    
                    # Save to DB
                    add_submission(student_name, exam['title'], essay_text, result)
                    
                    st.session_state.student_result = result
                    st.session_state.student_name_saved = student_name
                    st.session_state.student_submitted = True
                    st.rerun()
            else:
                st.warning("Please enter your name and write the essay before submitting!")

    else:
        st.success("Your work has been successfully submitted and graded!")
        
        with st.expander("Your Result & AI Feedback", expanded=True):
            st.markdown(st.session_state.student_result)
            
        st.markdown("---")
        col_btn1, col_btn2 = st.columns(2)
        
        with col_btn1:
            feedback_file_content = (
                f"Student: {st.session_state.student_name_saved}\n"
                f"Exam: {exam['title']}\n\n"
                f"=== RESULT AND FEEDBACK ===\n{st.session_state.student_result}"
            )
            
            st.download_button(
                label="📥 Download Feedback (TXT)",
                data=feedback_file_content,
                file_name=f"Result_{st.session_state.student_name_saved}.txt",
                mime="text/plain",
                use_container_width=True
            )
            
        with col_btn2:
            if st.button("🚪 Exit to Main Menu", use_container_width=True):
                st.session_state.student_submitted = False
                st.session_state.student_result = ""
                st.session_state.student_name_saved = ""
                st.session_state.role = None
                st.session_state.current_exam = None
                st.rerun()
