import streamlit as st
import sqlite3
import pandas as pd
from openai import OpenAI
import io

# --- 1. НАСТРОЙКИ СТРАНИЦЫ ---
st.set_page_config(
    page_title="AI Exam Platform", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# --- 2. ФУНКЦИЯ ЗАГРУЗКИ CSS ---
def load_css(file_name):
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except:
        pass

load_css("style.css")

# --- 3. ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('platform.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS exams (code TEXT PRIMARY KEY, title TEXT, desc TEXT, criteria TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, title TEXT, essay TEXT, grade TEXT)')
    conn.commit()
    return conn

db_conn = init_db()

# --- 4. СОСТОЯНИЕ СЕССИИ ---
if "role" not in st.session_state: 
    st.session_state.role = None
if "current_exam" not in st.session_state: 
    st.session_state.current_exam = None

# --- 5. УПРАВЛЕНИЕ САЙДБАРОМ (FIX NameError) ---
def manage_sidebar():
    if st.session_state.role == "Student":
        # Полностью скрываем для студента
        st.markdown("""
            <style>
                [data-testid="stSidebar"], [data-testid="collapsedControl"] {
                    display: none !important;
                }
            </style>
        """, unsafe_allow_html=True)
    else:
        # Принудительно показываем для Главной и Учителя
        st.markdown("""
            <style>
                [data-testid="stSidebar"], [data-testid="collapsedControl"] {
                    display: flex !important;
                }
            </style>
        """, unsafe_allow_html=True)

# ВЫЗЫВАЕМ ФУНКЦИЮ
manage_sidebar()

# --- 6. ЛОГИКА AI ---
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=st.secrets["API_KEY"].strip(),
)

def grade_essay(title, desc, criteria, essay):
    prompt = f"Grade this essay for '{title}'.\nTask: {desc}\nCriteria: {criteria}\nEssay: {essay}\nFormat: ### Grade: [X]/100\n### Feedback: [Text]"
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return response.choices[0].message.content

# --- 7. НАВИГАЦИЯ ---

# A. ГЛАВНОЕ МЕНЮ
if st.session_state.role is None:
    with st.sidebar:
        st.markdown("### Teacher Access")
        t_user = st.text_input("Username")
        t_pass = st.text_input("Password", type="password")
        if st.button("Login as Teacher", use_container_width=True):
            if t_user == "admin" and t_pass == "12345":
                st.session_state.role = "Teacher"
                st.rerun()
            else:
                st.error("Invalid Login")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try: st.image("Ai.png", use_container_width=True)
        except: pass
        st.markdown("<h1 style='text-align: center;'>Examination Portal</h1>", unsafe_allow_html=True)
        access_code = st.text_input("Enter Exam Code", placeholder="EXAM-101", label_visibility="collapsed")
        if st.button("Start Exam", type="primary", use_container_width=True):
            c = db_conn.cursor()
            c.execute("SELECT title, desc, criteria FROM exams WHERE code=?", (access_code,))
            res = c.fetchone()
            if res:
                st.session_state.current_exam = {"title": res[0], "desc": res[1], "criteria": res[2]}
                st.session_state.role = "Student"
                st.rerun()
            else:
                st.error("Exam code not found")

# B. ПАНЕЛЬ УЧИТЕЛЯ
elif st.session_state.role == "Teacher":
    with st.sidebar:
        st.title("Teacher Admin")
        if st.button("Logout"):
            st.session_state.role = None
            st.rerun()

    tab1, tab2 = st.tabs(["New Assignment", "Submissions"])
    
    with tab1:
        st.header("Create Assignment")
        nt = st.text_input("Exam Title")
        nd = st.text_area("Description")
        nc = st.text_input("Access Code")
        ncr = st.text_area("Grading Criteria")
        if st.button("Save and Publish"):
            try:
                c = db_conn.cursor()
                c.execute("INSERT INTO exams VALUES (?,?,?,?)", (nc, nt, nd, ncr))
                db_conn.commit()
                st.success("Exam Published!")
            except:
                st.error("Code already exists")

    with tab2:
        st.header("Results")
        c = db_conn.cursor()
        c.execute("SELECT name, title, essay, grade FROM submissions")
        data = c.fetchall()
        if data:
            df = pd.DataFrame(data, columns=["Name", "Exam", "Essay", "Grade"])
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 Download Results (CSV)", csv, "results.csv", "text/csv")
            for name, title, essay, grade in reversed(data):
                with st.expander(f"{name} - {title}"):
                    st.write(f"**Essay:** {essay}")
                    st.markdown(grade)
        else:
            st.info("No submissions yet")

# C. ЗОНА СТУДЕНТА
elif st.session_state.role == "Student":
    exam = st.session_state.current_exam
    st.title(f"Exam: {exam['title']}")
    
    with st.expander("Instruction"):
        st.write(exam['desc'])
        st.write(f"**Criteria:** {exam['criteria']}")
    
    s_name = st.text_input("Full Name")
    s_essay = st.text_area("Your Work", height=400)
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        if st.button("Submit Essay", type="primary"):
            if s_name and s_essay:
                with st.spinner("AI is checking..."):
                    grade = grade_essay(exam['title'], exam['desc'], exam['criteria'], s_essay)
                    c = db_conn.cursor()
                    c.execute("INSERT INTO submissions (name, title, essay, grade) VALUES (?,?,?,?)", (s_name, exam['title'], s_essay, grade))
                    db_conn.commit()
                    st.success("Work submitted and graded!")
                    st.markdown(grade)
            else:
                st.warning("Fill name and essay!")
    with col_s2:
        if st.button("Exit to Main Menu"):
            st.session_state.role = None
            st.rerun()
