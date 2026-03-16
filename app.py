import streamlit as st
import sqlite3
import pandas as pd
from openai import OpenAI
import io

# --- 1. CONFIG & CSS ---
st.set_page_config(page_title="AI Exam Platform", layout="wide")

def load_css(file_name):
    with open(file_name, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

try:
    load_css("style.css")
except:
    pass

# --- 2. DATABASE LOGIC ---
def init_db():
    conn = sqlite3.connect('platform.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS exams (code TEXT PRIMARY KEY, title TEXT, desc TEXT, criteria TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, title TEXT, essay TEXT, grade TEXT)')
    conn.commit()
    return conn

db_conn = init_db()

def get_exam_by_code(code):
    c = db_conn.cursor()
    c.execute("SELECT title, desc, criteria FROM exams WHERE code=?", (code,))
    res = c.fetchone()
    return {"title": res[0], "desc": res[1], "criteria": res[2]} if res else None

def add_submission(name, title, essay, grade):
    c = db_conn.cursor()
    c.execute("INSERT INTO submissions (name, title, essay, grade) VALUES (?, ?, ?, ?)", (name, title, essay, grade))
    db_conn.commit()

# --- 3. AI LOGIC ---
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

# --- 4. SESSION STATE ---
if "role" not in st.session_state: st.session_state.role = None
if "current_exam" not in st.session_state: st.session_state.current_exam = None

# --- 5. NAVIGATION ---

# A. LANDING PAGE
if st.session_state.role is None:
    # Sidebar: About & Teacher Login
    with st.sidebar:
        st.markdown("### About the Project")
        st.write("This platform uses AI to provide instant, fair, and detailed grading for student essays based on custom teacher criteria.")
        st.markdown("---")
        st.markdown("### Teacher Login")
        t_user = st.text_input("Login")
        t_pass = st.text_input("Password", type="password")
        if st.button("Access Dashboard"):
            if t_user == "admin" and t_pass == "12345":
                st.session_state.role = "Teacher"
                st.rerun()
            else:
                st.error("Invalid credentials")

    # Main: Large Logo & Student Code
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try: st.image("Ai.png", use_container_width=True)
        except: pass
        
        st.markdown("<h1 style='text-align: center;'>AI Examination Portal</h1>", unsafe_allow_html=True)
        access_code = st.text_input("Enter Access Code", placeholder="e.g. EXAM-101", label_visibility="collapsed")
        
        if st.button("Start My Exam", type="primary"):
            exam = get_exam_by_code(access_code)
            if exam:
                st.session_state.current_exam = exam
                st.session_state.role = "Student"
                st.rerun()
            else:
                st.error("Exam code not found.")

# B. TEACHER DASHBOARD
elif st.session_state.role == "Teacher":
    with st.sidebar:
        st.title("Teacher Admin")
        if st.button("Logout"):
            st.session_state.role = None
            st.rerun()

    tab1, tab2 = st.tabs(["New Assignment", "View Results"])
    
    with tab1:
        st.header("Create Assignment")
        nt = st.text_input("Title")
        nd = st.text_area("Task Description")
        nc = st.text_input("Access Code")
        ncr = st.text_area("Grading Criteria")
        if st.button("Save Exam"):
            c = db_conn.cursor()
            c.execute("INSERT INTO exams VALUES (?,?,?,?)", (nc, nt, nd, ncr))
            db_conn.commit()
            st.success("Exam Created!")

    with tab2:
        st.header("Students Submissions")
        c = db_conn.cursor()
        c.execute("SELECT name, title, essay, grade FROM submissions")
        data = c.fetchall()
        if data:
            df = pd.DataFrame(data, columns=["Name", "Exam", "Essay", "Grade"])
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 Export all to CSV", csv, "results.csv", "text/csv")
            
            for name, title, essay, grade in reversed(data):
                with st.expander(f"{name} - {title}"):
                    st.write(f"**Essay:** {essay}")
                    st.markdown(f"**AI Result:**\n{grade}")
        else:
            st.info("No submissions yet.")

# C. STUDENT AREA (No Sidebar)
elif st.session_state.role == "Student":
    # Hide sidebar for student via extra CSS
    st.markdown("<style>[data-testid='stSidebar'] {display:none;}</style>", unsafe_allow_html=True)
    
    exam = st.session_state.current_exam
    st.title(f"Exam: {exam['title']}")
    st.info(f"**Task:** {exam['desc']}\n\n**Criteria:** {exam['criteria']}")
    
    s_name = st.text_input("Your Full Name")
    s_essay = st.text_area("Your Essay", height=400)
    
    if st.button("Submit for Grading", type="primary"):
        if s_name and s_essay:
            with st.spinner("AI is grading your work..."):
                grade = grade_essay(exam['title'], exam['desc'], exam['criteria'], s_essay)
                add_submission(s_name, exam['title'], s_essay, grade)
                st.success("Work submitted!")
                st.markdown(grade)
                if st.button("Back to Menu"):
                    st.session_state.role = None
                    st.rerun()
        else:
            st.warning("Please fill name and essay.")
