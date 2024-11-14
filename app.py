from flask import Flask, render_template, request, Response, jsonify, flash, redirect, url_for, send_file
import cv2
import face_recognition
import sqlite3
import datetime
import numpy as np
from io import BytesIO
import pandas as pd
import os
from werkzeug.utils import secure_filename
import logging
from datetime import timedelta
import queue
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from pathlib import Path

app = Flask(__name__)
app.secret_key = 'jaijai2703'

class Config:
    UPLOAD_FOLDER = 'static/uploads'
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    SENDER_EMAIL = "jaijayakar27@gmail.com"  
    SENDER_PASSWORD = "thet akvq kzdp ejkn"   
    SECURITY_EMAIL = "jayakarraju.ss2021@vitstudent.ac.in"  
    FACE_RECOGNITION_TOLERANCE = 0.6
    MIN_FACE_SIZE = 20
    MAX_FAILED_ATTEMPTS = 3
    LOCKOUT_DURATION = timedelta(minutes=2)
    DB_PATH = 'campus_entry.db'
    BASE_URL = "http://localhost:5000"

os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

logging.basicConfig(
    filename='campus_entry.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

notification_queue = queue.Queue()

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

def init_db():
    conn = sqlite3.connect(Config.DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS authorized_data
                 (student_id TEXT PRIMARY KEY,
                  name TEXT,
                  face_encoding BLOB)''')
    c.execute('''CREATE TABLE IF NOT EXISTS captured_data
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  student_id TEXT,
                  face_encoding BLOB,
                  access_type TEXT,
                  entry_timestamp DATETIME,
                  exit_timestamp DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS unauthorized_attempts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  face_encoding BLOB,
                  timestamp DATETIME,
                  status TEXT)''')
    conn.commit()
    conn.close()

def get_camera():
    return cv2.VideoCapture(0)

def encode_face(frame):
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb_frame)
    if face_locations:
        face_encoding = face_recognition.face_encodings(rgb_frame, face_locations)[0]
        return face_encoding
    return None

def process_image_for_encoding(image_path):
    image = cv2.imread(image_path)
    if image is None:
        return None
    return encode_face(image)

def is_authorized(face_encoding):
    conn = sqlite3.connect(Config.DB_PATH)
    c = conn.cursor()
    c.execute("SELECT student_id, face_encoding FROM authorized_data")
    authorized_faces = c.fetchall()
    conn.close()
    for student_id, stored_encoding in authorized_faces:
        stored_encoding = np.frombuffer(stored_encoding, dtype=np.float64)
        if face_recognition.compare_faces([stored_encoding], face_encoding, 
                                        tolerance=Config.FACE_RECOGNITION_TOLERANCE)[0]:
            return student_id
    return None

class EmailNotifier:
    def __init__(self):
        self.context = ssl.create_default_context()
    
    def send_notification(self, image_path, details):
        try:
            message = MIMEMultipart()
            message["Subject"] = "Unauthorized Entry Attempt"
            message["From"] = Config.SENDER_EMAIL
            message["To"] = Config.SECURITY_EMAIL
            attempt_id = details.get('attempt_id')
            timestamp = details.get('timestamp')
            html = f"""
            <html>
                <body>
                    <h2>Unauthorized Entry Attempt Detected</h2>
                    <p>Timestamp: {timestamp}</p>
                    <p>Please verify the person's identity and approve or deny entry:</p>
                    <p>
                        <a href="{Config.BASE_URL}/security/verify/{attempt_id}/allow">Allow Entry</a>
                        <a href="{Config.BASE_URL}/security/verify/{attempt_id}/deny">Deny Entry</a>
                    </p>
                </body>
            </html>
            """
            message.attach(MIMEText(html, "html"))
            if image_path and os.path.exists(image_path):
                with open(image_path, 'rb') as f:
                    img_data = f.read()
                    image = MIMEImage(img_data)
                    image.add_header('Content-ID', '<captured_image>')
                    message.attach(image)
            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
                server.starttls(context=self.context)
                server.login(Config.SENDER_EMAIL, Config.SENDER_PASSWORD)
                server.send_message(message)
            logging.info(f"Security notification email sent for attempt ID: {attempt_id}")
            return True
        except Exception as e:
            logging.error(f"Failed to send security notification email: {str(e)}")
            return False

email_notifier = EmailNotifier()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/add_authorized', methods=['GET', 'POST'])
def add_authorized():
    if request.method == 'POST':
        student_id = request.form['student_id']
        name = request.form['name']
        image_source = request.form.get('image_source')
        face_encoding = None
        if image_source == 'upload':
            if 'file' not in request.files:
                flash('No file uploaded', 'error')
                return redirect(request.url)
            file = request.files['file']
            if file.filename == '':
                flash('No file selected', 'error')
                return redirect(request.url)
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(Config.UPLOAD_FOLDER, filename)
                file.save(filepath)
                face_encoding = process_image_for_encoding(filepath)
                os.remove(filepath)
        elif image_source == 'capture':
            camera = get_camera()
            ret, frame = camera.read()
            camera.release()
            if ret:
                face_encoding = encode_face(frame)
        if face_encoding is not None:
            try:
                conn = sqlite3.connect(Config.DB_PATH)
                c = conn.cursor()
                c.execute("INSERT INTO authorized_data VALUES (?, ?, ?)",
                         (student_id, name, face_encoding.tobytes()))
                conn.commit()
                flash('Person added successfully!', 'success')
            except sqlite3.IntegrityError:
                flash('Student ID already exists!', 'error')
            finally:
                conn.close()
        else:
            flash('No face detected in the image!', 'error')
        return redirect(url_for('add_authorized'))
    return render_template('add_authorized.html')

def gen_frames():
    camera = get_camera()
    while True:
        success, frame = camera.read()
        if not success:
            break
        else:
            frame = cv2.resize(frame, (640, 480))
            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/process_entry', methods=['POST'])
def process_entry():
    camera = get_camera()
    ret, frame = camera.read()
    camera.release()
    if ret:
        face_encoding = encode_face(frame)
        if face_encoding is not None:
            student_id = is_authorized(face_encoding)
            if student_id:
                conn = sqlite3.connect(Config.DB_PATH)
                c = conn.cursor()
                c.execute("""INSERT INTO captured_data 
                           (student_id, face_encoding, access_type, entry_timestamp)
                           VALUES (?, ?, ?, ?)""",
                        (student_id, face_encoding.tobytes(), 'authorized', 
                         datetime.datetime.now()))
                conn.commit()
                conn.close()
                return jsonify({'status': 'success', 'message': 'Authorized entry recorded'})
            else:
                conn = sqlite3.connect(Config.DB_PATH)
                c = conn.cursor()
                timestamp = datetime.datetime.now()
                c.execute("""INSERT INTO unauthorized_attempts 
                           (face_encoding, timestamp, status)
                           VALUES (?, ?, ?)""",
                        (face_encoding.tobytes(), timestamp, 'pending'))
                attempt_id = c.lastrowid
                conn.commit()
                conn.close()
                img_path = os.path.join(Config.UPLOAD_FOLDER, f'unauthorized_{attempt_id}.jpg')
                cv2.imwrite(img_path, frame)
                notification_queue.put((img_path, {
                    'attempt_id': attempt_id,
                    'timestamp': timestamp
                }))
                return jsonify({'status': 'warning', 
                              'message': 'Unauthorized person detected - Security notified'})
        else:
            return jsonify({'status': 'error', 'message': 'No face detected'})
    return jsonify({'status': 'error', 'message': 'Camera error'})

@app.route('/process_exit', methods=['POST'])
def process_exit():
    camera = get_camera()
    ret, frame = camera.read()
    camera.release()
    if ret:
        face_encoding = encode_face(frame)
        if face_encoding is not None:
            student_id = is_authorized(face_encoding)
            if student_id:
                conn = sqlite3.connect(Config.DB_PATH)
                c = conn.cursor()
                c.execute("""UPDATE captured_data 
                           SET exit_timestamp = ? 
                           WHERE student_id = ? 
                           AND exit_timestamp IS NULL""",
                        (datetime.datetime.now(), student_id))
                conn.commit()
                conn.close()
                return jsonify({'status': 'success', 'message': 'Exit recorded'})
            else:
                return jsonify({'status': 'error', 
                              'message': 'Person not found in system'})
        else:
            return jsonify({'status': 'error', 'message': 'No face detected'})
    return jsonify({'status': 'error', 'message': 'Camera error'})

@app.route('/security/verify/<int:attempt_id>/<string:decision>')
def security_verify(attempt_id, decision):
    try:
        conn = sqlite3.connect(Config.DB_PATH)
        c = conn.cursor()
        c.execute("""SELECT face_encoding, timestamp, status 
                    FROM unauthorized_attempts WHERE id = ?""", 
                 (attempt_id,))
        result = c.fetchone()
        if not result:
            return render_template('error.html', 
                                message="Invalid or expired verification link")
        face_encoding, timestamp, status = result
        if status != 'pending':
            return render_template('error.html', 
                                message="This entry attempt has already been processed")
        if decision == 'allow':
            temp_id = f'TEMP_{attempt_id}_{datetime.datetime.now().strftime("%Y%m%d")}'
            c.execute("""INSERT INTO captured_data 
                       (student_id, face_encoding, access_type, entry_timestamp)
                       VALUES (?, ?, ?, ?)""",
                    (temp_id, face_encoding, 'temporary', timestamp))
            c.execute("""UPDATE unauthorized_attempts 
                       SET status = 'approved' WHERE id = ?""",
                     (attempt_id,))
            conn.commit()
            return render_template('verification_result.html', 
                                message="Entry approved", 
                                temp_id=temp_id)
        elif decision == 'deny':
            c.execute("""UPDATE unauthorized_attempts 
                       SET status = 'denied' WHERE id = ?""",
                     (attempt_id,))
            conn.commit()
            return render_template('verification_result.html', 
                                message="Entry denied")
        else:
            return render_template('error.html', 
                                message="Invalid decision")
    except Exception as e:
        logging.error(f"Error in security verification: {str(e)}")
        return render_template('error.html', 
                            message="An error occurred during verification")
    finally:
        conn.close()
        
@app.route('/download_data/<table_name>')
def download_data(table_name):
    conn = sqlite3.connect(Config.DB_PATH)
    if table_name == 'authorized':
        df = pd.read_sql_query("SELECT student_id, name FROM authorized_data", conn)
    else:
        df = pd.read_sql_query("""SELECT student_id, access_type, 
                                 entry_timestamp, exit_timestamp 
                                 FROM captured_data""", conn)
    conn.close()
    output = BytesIO()
    df.to_csv(output, index=False)
    output.seek(0)
    return send_file(
        output,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'{table_name}_data.csv'
    )

@app.route('/reports')
def reports():
    conn = sqlite3.connect(Config.DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM authorized_data")
    total_authorized = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM captured_data WHERE access_type='authorized'")
    total_entries = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM unauthorized_attempts")
    total_unauthorized = c.fetchone()[0]
    c.execute("""SELECT cd.student_id, ad.name, cd.entry_timestamp, cd.exit_timestamp
                 FROM captured_data cd
                 LEFT JOIN authorized_data ad ON cd.student_id = ad.student_id
                 ORDER BY cd.entry_timestamp DESC LIMIT 10""")
    recent_entries = c.fetchall()
    conn.close()
    return render_template('reports.html',
                         total_authorized=total_authorized,
                         total_entries=total_entries,
                         total_unauthorized=total_unauthorized,
                         recent_entries=recent_entries)

@app.route('/live_monitoring')
def live_monitoring():
    return render_template('live_monitoring.html')

@app.route('/check_status')
def check_status():
    try:
        camera = get_camera()
        camera_status = camera.isOpened()
        if camera_status:
            camera.release()
        conn = sqlite3.connect(Config.DB_PATH)
        conn.cursor()
        db_status = True
        conn.close()
        return jsonify({
            'status': 'operational' if (camera_status and db_status) else 'issues detected',
            'camera': 'operational' if camera_status else 'not working',
            'database': 'connected' if db_status else 'connection failed',
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        logging.error(f"Status check failed: {str(e)}")
        return jsonify({
            'status': 'system error',
            'error': str(e),
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }), 500

def notification_worker():
    while True:
        try:
            notification = notification_queue.get()
            if notification is None:
                break
            image_path, details = notification
            email_notifier.send_notification(image_path, details)
            if os.path.exists(image_path):
                os.remove(image_path)
            notification_queue.task_done()
        except Exception as e:
            logging.error(f"Error in notification worker: {str(e)}")

@app.route('/manage_authorized', methods=['GET'])
def manage_authorized():
    conn = sqlite3.connect(Config.DB_PATH)
    c = conn.cursor()
    c.execute("SELECT student_id, name FROM authorized_data ORDER BY name")
    authorized_list = c.fetchall()
    conn.close()
    return render_template('manage_authorized.html', authorized_list=authorized_list)

@app.route('/delete_authorized/<student_id>', methods=['POST'])
def delete_authorized(student_id):
    try:
        conn = sqlite3.connect(Config.DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM authorized_data WHERE student_id = ?", (student_id,))
        conn.commit()
        conn.close()
        flash('Person removed successfully', 'success')
    except Exception as e:
        flash(f'Error removing person: {str(e)}', 'error')
    return redirect(url_for('manage_authorized'))

@app.route('/edit_authorized/<student_id>', methods=['GET', 'POST'])
def edit_authorized(student_id):
    if request.method == 'POST':
        name = request.form['name']
        try:
            conn = sqlite3.connect(Config.DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE authorized_data SET name = ? WHERE student_id = ?",
                     (name, student_id))
            conn.commit()
            conn.close()
            flash('Person updated successfully', 'success')
            return redirect(url_for('manage_authorized'))
        except Exception as e:
            flash(f'Error updating person: {str(e)}', 'error')
    conn = sqlite3.connect(Config.DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM authorized_data WHERE student_id = ?", (student_id,))
    result = c.fetchone()
    conn.close()
    if result is None:
        flash('Person not found', 'error')
        return redirect(url_for('manage_authorized'))
    return render_template('edit_authorized.html',
                         student_id=student_id,
                         name=result[0])

@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html',
                         message="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    logging.error(f"Internal server error: {str(error)}")
    return render_template('error.html',
                         message="Internal server error"), 500

if __name__ == '__main__':
    init_db()
    import threading
    notification_thread = threading.Thread(target=notification_worker, daemon=True)
    notification_thread.start()
    app.run(debug=True, host='0.0.0.0', port=5000)
