import streamlit as st
import sqlite3
import pandas as pd
from openai import OpenAI

# 1. Принудительно разворачиваем сайдбар в конфиге
st.set_page_config(
    page_title="AdilEduAssessment", 
    layout="wide", 
    initial_sidebar_state="expanded" 
)

# 2. Загрузка CSS
def load_css(file_name):
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except:
        pass

load_css("style.css")

# 3. СИЛОВОЙ ФИКС САЙДБАРА (Вставлять сразу после load_css)
if st.session_state.get("role") != "Student":
    st.markdown("""
        <style>
            section[data-testid="stSidebar"] {
                display: flex !important;
                visibility: visible !important;
                width: 300px !important;
            }
            [data-testid="collapsedControl"] {
                display: flex !important;
            }
        </style>
    """, unsafe_allow_html=True)
# --- 3. DATABASE ---
def init_db():
    conn = sqlite3.connect('platform.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS exams (code TEXT PRIMARY KEY, title TEXT, desc TEXT, criteria TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, title TEXT, essay TEXT, grade TEXT)')
    conn.commit()
    return conn

db_conn = init_db()

# --- 4. SESSION STATE ---
if "role" not in st.session_state: st.session_state.role = None
if "current_exam" not in st.session_state: st.session_state.current_exam = None

# --- 5. AI LOGIC ---
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

# --- 6. NAVIGATION ---

# ГЛАВНЫЙ ЭКРАН
if st.session_state.role is None:
    with st.sidebar:
        st.markdown("### Teacher Login")
        t_user = st.text_input("Username")
        t_pass = st.text_input("Password", type="password")
        if st.button("Login"):
            if t_user == "admin" and t_pass == "12345":
                st.session_state.role = "Teacher"
                st.rerun()

    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown('<p class="logo-text">AdilEduAssessment</p>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<p style='text-align: center; opacity: 0.7;'>Enter access code to start</p>", unsafe_allow_html=True)
        access_code = st.text_input("Code", placeholder="EXAM-CODE", label_visibility="collapsed")
        if st.button("Start Exam", type="primary"):
            c = db_conn.cursor()
            c.execute("SELECT title, desc, criteria FROM exams WHERE code=?", (access_code,))
            res = c.fetchone()
            if res:
                st.session_state.current_exam = {"title": res[0], "desc": res[1], "criteria": res[2]}
                st.session_state.role = "Student"
                st.rerun()
            else:
                st.error("Code not found")

# ПАНЕЛЬ УЧИТЕЛЯ
elif st.session_state.role == "Teacher":
    st.sidebar.button("Logout", on_click=lambda: st.session_state.update({"role": None}))
    st.markdown("## Teacher Dashboard")
    
    tab1, tab2 = st.tabs(["Add Assignment", "View Results"])
    with tab1:
        with st.form("add_ex"):
            nt = st.text_input("Title")
            nd = st.text_area("Task")
            nc = st.text_input("Code")
            ncr = st.text_area("Criteria")
            if st.form_submit_button("Save Exam"):
                c = db_conn.cursor()
                c.execute("INSERT OR REPLACE INTO exams VALUES (?,?,?,?)", (nc, nt, nd, ncr))
                db_conn.commit()
                st.success("Exam Saved!")
    with tab2:
        c = db_conn.cursor()
        c.execute("SELECT name, title, essay, grade FROM submissions")
        data = c.fetchall()
        if data:
            df = pd.DataFrame(data, columns=["Name", "Exam", "Essay", "Grade"])
            st.download_button("Export CSV", df.to_csv(index=False).encode('utf-8-sig'), "results.csv")
            for r in reversed(data):
                with st.expander(f"{r[0]} - {r[1]}"):
                    st.write(r[2])
                    st.info(r[3])

# СТУДЕНТ
elif st.session_state.role == "Student":
    st.markdown("<style>[data-testid='stSidebar'] {display:none !important;}</style>", unsafe_allow_html=True)
    exam = st.session_state.current_exam
    st.markdown(f'<p class="logo-text" style="font-size: 32px !important;">{exam["title"]}</p>', unsafe_allow_html=True)
    
    st.write(exam['desc'])
    s_name = st.text_input("Your Name")
    s_essay = st.text_area("Your Essay", height=350)
    
    if st.button("Submit Work", type="primary"):
        if s_name and s_essay:
            with st.spinner("AI is grading..."):
                grade = grade_essay(exam['title'], exam['desc'], exam['criteria'], s_essay)
                c = db_conn.cursor()
                c.execute("INSERT INTO submissions (name, title, essay, grade) VALUES (?,?,?,?)", (s_name, exam['title'], s_essay, grade))
                db_conn.commit()
                st.success("Done!")
                st.markdown(grade)
        else: st.warning("Fill all fields")
    
    if st.button("Exit"):
        st.session_state.role = None
        st.rerun()
