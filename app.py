from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename # สำหรับจัดการชื่อไฟล์อัพโหลด
from datetime import datetime
import sqlite3
from io import BytesIO
import os

# ไลบรารีสำหรับสร้าง PDF
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

app = Flask(__name__)
app.secret_key = 'super_secret_key'

# --- [CONFIG อัพโหลดรูปภาพ] ---
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- [DATABASE CONFIG] ---
def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    # ตารางเดิมของคุณ (ห้ามลบ)
    conn.execute('CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, action TEXT, time TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, email TEXT, role TEXT)')
    conn.execute('''CREATE TABLE IF NOT EXISTS suggestions 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, title TEXT, 
                     year INTEGER, type TEXT, category TEXT, summary TEXT, status TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS items 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, img TEXT, 
                     category TEXT, type TEXT, description TEXT, year INTEGER, date_added TEXT)''')
    
    # --- เพิ่มตาราง reviews ตรงนี้ ---
    conn.execute('''CREATE TABLE IF NOT EXISTS reviews 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                     movie_id INTEGER NOT NULL, 
                     username TEXT NOT NULL, 
                     content TEXT NOT NULL, 
                     timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    # -----------------------------

    hashed_admin_pw = generate_password_hash('123')
    conn.execute("INSERT OR IGNORE INTO users (username, password, email, role) VALUES (?, ?, ?, ?)", 
                 ('admin1', hashed_admin_pw, 'admin@mail.com', 'admin'))
    
    conn.commit()
    conn.close()

def add_log(action):
    user = session.get('username', 'Guest')
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    conn.execute("INSERT INTO logs (user, action, time) VALUES (?, ?, ?)", (user, action, time_str))
    conn.commit()
    conn.close()

# --- [USER ROUTES] ---

@app.route('/')
def index():
    search_query = request.args.get('search', '').lower()
    type_filter = request.args.get('type', 'all')
    selected_cats = request.args.getlist('category') 

    conn = get_db_connection()
    query = "SELECT * FROM items WHERE 1=1"
    params = []
    if search_query:
        query += " AND LOWER(title) LIKE ?"
        params.append(f"%{search_query}%")
    if type_filter != 'all':
        query += " AND type = ?"
        params.append(type_filter)

    items = conn.execute(query, params).fetchall()
    if selected_cats:
        items = [i for i in items if i['category'].lower() in [c.lower() for c in selected_cats]]

    db_logs = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 10").fetchall()
    conn.close()
    return render_template('index.html', items=items, user_logs=db_logs)

@app.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    conn = get_db_connection()
    
    # ดึงข้อมูลหนัง (เพื่อให้ {{ movie.title }}, {{ movie.description }} ทำงานได้)
    movie = conn.execute('SELECT * FROM items WHERE id = ?', (movie_id,)).fetchone()
    
    # ดึงข้อมูลรีวิว (เพื่อให้ส่วนรายการรีวิวด้านล่างทำงานได้)
    reviews = conn.execute('''
        SELECT username, content, strftime('%d/%m/%Y %H:%M', timestamp, 'localtime') as timestamp 
        FROM reviews WHERE movie_id = ? ORDER BY id DESC
    ''', (movie_id,)).fetchall()
    
    conn.close()
    
    # ต้องส่งทั้ง movie และ reviews กลับไปที่ไฟล์ HTML
    return render_template('detail.html', movie=movie, reviews=reviews, movie_id=movie_id)

@app.route('/add_review/<int:movie_id>', methods=['POST'])
def add_review(movie_id):
    # ตรวจสอบว่าเข้าสู่ระบบหรือยัง (ถ้ามีระบบ Login)
    if 'username' not in session:
        return redirect(url_for('login'))
    
    # รับข้อความจากฟอร์ม (input ที่ชื่อ name="comment")
    content = request.form.get('comment')
    username = session.get('username')
    
    if content:
        conn = get_db_connection()
        # บันทึกลงตาราง reviews ที่เราสร้างไว้ใน init_db
        conn.execute('INSERT INTO reviews (movie_id, username, content) VALUES (?, ?, ?)',
                     (movie_id, username, content))
        conn.commit()
        conn.close()
    
    # เมื่อบันทึกเสร็จ ให้ดีดกลับไปหน้ารายละเอียดหนังเรื่องเดิม
    return redirect(url_for('movie_detail', movie_id=movie_id))

@app.route('/suggest_movie', methods=['GET', 'POST'])
def suggest_movie():
    if 'username' not in session:
        flash("กรุณาเข้าสู่ระบบก่อนแนะนำหนัง")
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form.get('title')
        year = request.form.get('year')
        m_type = request.form.get('type')
        category = request.form.get('category')
        summary = request.form.get('summary')
        
        conn = get_db_connection()
        conn.execute('''INSERT INTO suggestions (username, title, year, type, category, summary, status) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                     (session['username'], title, year, m_type, category, summary, 'pending'))
        conn.commit()
        conn.close()
        flash("ส่งคำแนะนำเรียบร้อยแล้ว!")
        return redirect(url_for('index'))
    return render_template('suggest_movie.html')

# --- [ADMIN ROUTES] ---

@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = get_db_connection()
    m_count = conn.execute("SELECT COUNT(*) FROM items WHERE type='movie'").fetchone()[0]
    s_count = conn.execute("SELECT COUNT(*) FROM items WHERE type='series'").fetchone()[0]
    u_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    g_count = conn.execute("SELECT COUNT(*) FROM suggestions WHERE status='pending'").fetchone()[0]
    conn.close()
    return render_template('admin_dashboard.html', m_count=m_count, s_count=s_count, u_count=u_count, g_count=g_count)

@app.route('/admin/manage')
def admin_manage():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = get_db_connection()
    items = conn.execute("SELECT * FROM items ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('admin_manage.html', items=items)

# --- เพิ่มเติม: หน้าฟอร์มเพิ่มหนังและอัพโหลดรูป ---
@app.route('/admin/add_movie', methods=['GET', 'POST'])
def add_movie():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        year = request.form.get('year')
        m_type = request.form.get('type')
        category = request.form.get('category')
        description = request.form.get('description')
        
        # จัดการไฟล์รูปภาพ
        file = request.files.get('poster')
        img_path = '/static/images/placeholder.jpg' # ค่าเริ่มต้นถ้าไม่ใส่รูป
        
        if file and allowed_file(file.filename):
            # ตั้งชื่อไฟล์ใหม่ด้วย timestamp ป้องกันชื่อซ้ำ
            filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            img_path = f'/static/uploads/{filename}'
        
        date_now = datetime.now().strftime("%Y-%m-%d")
        conn = get_db_connection()
        conn.execute('''INSERT INTO items (title, img, category, type, description, year, date_added) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                     (title, img_path, category, m_type, description, year, date_now))
        conn.commit()
        conn.close()
        
        add_log(f"เพิ่มข้อมูลใหม่: {title}")
        flash("เพิ่มข้อมูลภาพยนตร์/ซีรีส์สำเร็จ!")
        return redirect(url_for('admin_manage'))
        
    return render_template('admin_add_movie.html')

@app.route('/admin/members')
def admin_members():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = get_db_connection()
    users = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    return render_template('admin_members.html', users=users)

@app.route('/admin/suggestions')
def admin_suggestions():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = get_db_connection()
    suggests = conn.execute("SELECT * FROM suggestions ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('admin_suggestions.html', suggests=suggests)

@app.route('/admin/approve/<int:sug_id>')
def approve_suggestion(sug_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = get_db_connection()
    sug = conn.execute("SELECT * FROM suggestions WHERE id = ?", (sug_id,)).fetchone()
    if sug:
        date_now = datetime.now().strftime("%Y-%m-%d")
        conn.execute('''INSERT INTO items (title, img, category, type, description, year, date_added) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                     (sug['title'], '/static/images/placeholder.jpg', sug['category'], sug['type'], sug['summary'], sug['year'], date_now))
        conn.execute("UPDATE suggestions SET status = 'approved' WHERE id = ?", (sug_id,))
        conn.commit()
        add_log(f"อนุมัติคำแนะนำ: {sug['title']}")
    conn.close()
    return redirect(url_for('admin_suggestions'))

@app.route('/admin/update_role/<username>', methods=['POST'])
def update_role(username):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    new_role = request.form.get('new_role')
    conn = get_db_connection()
    conn.execute("UPDATE users SET role = ? WHERE username = ?", (new_role, username))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_members'))

# --- [REPORT SYSTEM] ---

@app.route('/admin/report')
def admin_report():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    return render_template('admin_report.html')

@app.route('/admin/export_pdf', methods=['POST'])
def export_pdf():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    
    report_type = request.form.get('report_type')
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    
    conn = get_db_connection()
    if report_type == 'items':
        query = "SELECT * FROM items WHERE date_added BETWEEN ? AND ?"
        data = conn.execute(query, (start_date, end_date)).fetchall()
        report_title = f"Movie & Series Report ({start_date} to {end_date})"
    else:
        query = "SELECT * FROM logs WHERE time BETWEEN ? AND ?"
        data = conn.execute(query, (start_date + " 00:00:00", end_date + " 23:59:59")).fetchall()
        report_title = f"System Usage Logs ({start_date} to {end_date})"
    conn.close()

    buffer = BytesIO()
    p = canvas.Canvas(buffer)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, 800, report_title)
    
    y = 750
    p.setFont("Helvetica", 10)
    for row in data:
        if y < 50:
            p.showPage()
            y = 800
        
        if report_type == 'items':
            line = f"- {row['title']} | Type: {row['type']} | Added: {row['date_added']}"
        else:
            line = f"[{row['time']}] {row['user']}: {row['action']}"
            
        p.drawString(50, y, line)
        y -= 20
        
    p.showPage()
    p.save()
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True, download_name=f"report_{report_type}.pdf", mimetype='application/pdf')

# --- [AUTH ROUTES] ---

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        if password != confirm_password:
            flash("รหัสผ่านไม่ตรงกัน!")
            return redirect(url_for('signup'))
        db = get_db_connection()
        user_exists = db.execute('SELECT 1 FROM users WHERE username = ?', (username,)).fetchone()
        if user_exists:
            flash("ชื่อผู้ใช้นี้ถูกใช้ไปแล้ว!")
            db.close()
            return redirect(url_for('signup'))
        hashed_pw = generate_password_hash(password)
        db.execute('INSERT INTO users (username, password, email, role) VALUES (?, ?, ?, ?)',
                   (username, hashed_pw, f"{username}@example.com", 'viewer'))
        db.commit()
        db.close()
        flash("สมัครสมาชิกสำเร็จ! กรุณาเข้าสู่ระบบ")
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        db = get_db_connection()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        db.close()
        if user and check_password_hash(user['password'], password):
            session['username'] = user['username']
            session['role'] = user['role']
            add_log("Login เข้าระบบ")
            return redirect(url_for('index'))
        else:
            flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    return render_template('login.html')

@app.route('/logout')
def logout():
    add_log("Logout ออกจากระบบ")
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)