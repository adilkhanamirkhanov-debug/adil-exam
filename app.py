import streamlit as st
import sqlite3
import pandas as pd
from openai import OpenAI
import random
import string
import time # Добавили библиотеку для работы со временем
import mammoth 

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

# --- 3. SIDEBAR FIX & SESSION STATE ---
if "role" not in st.session_state: st.session_state.role = None
if "gen_code" not in st.session_state: st.session_state.gen_code = ""
if "exam_submitted" not in st.session_state: st.session_state.exam_submitted = False
if "student_grade" not in st.session_state: st.session_state.student_grade = ""
if "exam_end_time" not in st.session_state: st.session_state.exam_end_time = None

if st.session_state.role != "Student":
    st.markdown("""<style>[data-testid="collapsedControl"] {display: flex !important; top: 25px !important;} section[data-testid="stSidebar"] {display: flex !important;}</style>""", unsafe_allow_html=True)
else:
    st.markdown("""<style>[data-testid="collapsedControl"], section[data-testid="stSidebar"] {display: none !important;}</style>""", unsafe_allow_html=True)

# --- 4. DATABASE ---
def init_db():
    conn = sqlite3.connect('platform.db', check_same_thread=False)
    c = conn.cursor()
    # Обновили таблицу до v3, чтобы добавить поле time_limit
    c.execute('CREATE TABLE IF NOT EXISTS exams_v3 (code TEXT PRIMARY KEY, type TEXT, title TEXT, desc TEXT, criteria TEXT, strictness REAL, time_limit INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, title TEXT, essay TEXT, grade TEXT)')
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
        st.markdown("### Teacher Login")
        t_user = st.text_input("Username")
        t_pass = st.text_input("Password", type="password")
        if st.button("Login", type="primary"):
            if t_user == "admin" and t_pass == "12345":
                st.session_state.role = "Teacher"
                st.rerun()

    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown('<p class="logo-text">AdilEduAssessment</p>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<p style='text-align: center; opacity: 0.7;'>Выберите формат сдачи и введите код доступа</p>", unsafe_allow_html=True)
        
        student_mode = st.radio("Режим экзамена:", ["Стандартный экзамен", "Экзамен MYP"], horizontal=True)
        access_code = st.text_input("Код", placeholder="Например: MYP-1A2B3", label_visibility="collapsed")
        
        if st.button("Начать экзамен", type="primary"):
            c = db_conn.cursor()
            c.execute("SELECT type, title, desc, criteria, strictness, time_limit FROM exams_v3 WHERE code=?", (access_code,))
            res = c.fetchone()
            if res:
                db_type = res[0]
                selected_type = "Quick" if student_mode == "Стандартный экзамен" else "MYP"
                
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
                    # Устанавливаем таймер
                    if res[5] > 0:
                        st.session_state.exam_end_time = time.time() + (res[5] * 60)
                    else:
                        st.session_state.exam_end_time = None
                    st.rerun()
            else:
                st.error("Код не найден или введен неверно.")

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
        st.header("Быстрые задачи (Базовый вариант)")
        with st.form("quick_exam"):
            nt = st.text_input("Название экзамена")
            nd = st.text_area("Описание задачи (Поддерживает HTML)")
            
            # Поле для времени
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
                    c = db_conn.cursor()
                    c.execute("INSERT OR REPLACE INTO exams_v3 VALUES (?,?,?,?,?,?,?)", (nc, "Quick", nt, nd, ncr, 5.0, t_limit))
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
        # Поле для времени MYP
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

                c = db_conn.cursor()
                c.execute("INSERT OR REPLACE INTO exams_v3 VALUES (?,?,?,?,?,?,?)", (nc, "MYP", nt, final_desc, final_crit, float(strictness), t_limit))
                db_conn.commit()
                st.success(f"MYP Экзамен опубликован! Код доступа: {nc}")
            else:
                st.warning("Пожалуйста, введите название и сгенерируйте код.")

    elif menu_selection == "Кастомные задачи":
        st.header("Кастомные задачи")
        st.info("Этот раздел находится в разработке.")

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
                    st.markdown("**Ответ:**", unsafe_allow_html=True)
                    st.markdown(r[2], unsafe_allow_html=True)
                    st.info(f"**Оценка ИИ:**\n{r[3]}")
        else:
            st.info("Пока нет ни одной сданной работы.")

# СТУДЕНТ
elif st.session_state.role == "Student":
    import streamlit.components.v1 as components 
    
    exam = st.session_state.current_exam
    is_time_up = False
    remaining_seconds = 0
    
    # Считаем время на стороне Python
    if st.session_state.exam_end_time and not st.session_state.exam_submitted:
        remaining_seconds = int(st.session_state.exam_end_time - time.time())
        if remaining_seconds <= 0:
            is_time_up = True

    # Заголовок теперь на всю ширину (без таймера справа сверху)
    mode_label = "Режим IB MYP" if exam["type"] == "MYP" else "Стандартный режим"
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
                st.rerun()
                
        else:
            st.markdown("### Ваш ответ")
            s_name = st.text_input("Ваше полное имя (Имя и Фамилия)")
            
            # УВЕЛИЧЕННОЕ ПОЛЕ ДЛЯ ОТВЕТА (height=500 вместо 250)
            if is_time_up:
                st.error("Время, отведенное на экзамен, закончилось.")
                s_essay = st.text_area("Напишите ваш ответ здесь...", height=500, disabled=True)
            else:
                s_essay = st.text_area("Напишите ваш ответ здесь...", height=500)
            
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
                if st.button("Выйти на главную", type="secondary"):
                    st.session_state.role = None
                    st.rerun()

    with col_right:
        st.markdown("### Критерии оценивания")
        # Немного уменьшили высоту контейнера с критериями, чтобы влез таймер
        with st.container(height=450):
            st.markdown(exam["criteria"], unsafe_allow_html=True)
            
        st.markdown("---") # Визуальный разделитель
        
        # ТАЙМЕР ТЕПЕРЬ ЗДЕСЬ (ПОД КРИТЕРИЯМИ)
        if st.session_state.exam_end_time and not st.session_state.exam_submitted:
            if not is_time_up:
                timer_html = f"""
                <div id="exam-timer" style="font-family: sans-serif; font-size: 20px; font-weight: bold; color: #ff4b4b; background: rgba(255, 75, 75, 0.1); padding: 15px; border-radius: 8px; border: 2px solid #ff4b4b; text-align: center;">
                 Запуск таймера...
                </div>
                <script>
                var secondsLeft = {remaining_seconds};
                var timerInterval = setInterval(function() {{
                    secondsLeft--;
                    var m = Math.floor(secondsLeft / 60);
                    var s = secondsLeft % 60;
                    if (s < 10) {{ s = "0" + s; }}
                    document.getElementById("exam-timer").innerHTML = " Осталось: " + m + ":" + s;
                    if (secondsLeft <= 0) {{
                        clearInterval(timerInterval);
                        document.getElementById("exam-timer").innerHTML = " Время вышло!";
                    }}
                }}, 1000);
                </script>
                """
                components.html(timer_html, height=80)
            else:
                st.markdown("""
                <div style="font-size: 20px; font-weight: bold; color: #ff4b4b; background: rgba(255, 75, 75, 0.1); padding: 15px; border-radius: 8px; border: 2px solid #ff4b4b; text-align: center;">
                 Время вышло!
                </div>
                """, unsafe_allow_html=True)
