import os
import secrets
from datetime import datetime

from flask import Flask, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_socketio import SocketIO, send, join_room
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
@app.after_request
def after_request(response):
    response.headers['ngrok-skip-browser-warning'] = 'true'
    return response

app.config['SECRET_KEY'] = 'studygroup_secret_key_2024_xk92'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///study.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'txt', 'md', 'docx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

ALLOWED_ORIGINS = [
    'http://127.0.0.1:5500',
    'http://localhost:5500',
    'https://glowing-fudge-cfba84.netlify.app'
]

CORS(app,
     supports_credentials=True,
     origins=ALLOWED_ORIGINS,
     allow_headers=['Content-Type'],
     methods=['GET', 'POST', 'OPTIONS'])

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
socketio = SocketIO(app,
                    cors_allowed_origins=ALLOWED_ORIGINS,
                    manage_session=False)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.after_request
def after_request(response):
    response.headers['Access-Control-Allow-Origin'] = 'https://glowing-fudge-cfba84.netlify.app'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['ngrok-skip-browser-warning'] = 'true'
    return response


# ── Helpers ──────────────────────────────────────

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_logged_in():
    return 'user_id' in session

def is_group_member(group_id):
    return GroupMember.query.filter_by(
        user_id=session['user_id'], group_id=group_id
    ).first() is not None

def err(msg, status):
    return jsonify({'msg': msg}), status

def ok(msg, **kwargs):
    return jsonify({'msg': msg, **kwargs}), 200


# ── Models ───────────────────────────────────────

class User(db.Model):
    __tablename__ = 'users'
    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(100), nullable=False)
    email    = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    memberships = db.relationship('GroupMember', backref='user', cascade='all, delete-orphan')
    messages    = db.relationship('Message',     backref='user', cascade='all, delete-orphan')

class Group(db.Model):
    __tablename__ = 'groups'
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    created_by  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    members  = db.relationship('GroupMember',  backref='group', cascade='all, delete-orphan')
    sessions = db.relationship('StudySession', backref='group', cascade='all, delete-orphan')
    notes    = db.relationship('Note',         backref='group', cascade='all, delete-orphan')
    messages = db.relationship('Message',      backref='group', cascade='all, delete-orphan')

class GroupMember(db.Model):
    __tablename__ = 'group_members'
    id       = db.Column(db.Integer, primary_key=True)
    user_id  = db.Column(db.Integer, db.ForeignKey('users.id'),  nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'group_id'),)

class StudySession(db.Model):
    __tablename__ = 'study_sessions'
    id       = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    title    = db.Column(db.String(100), nullable=False)
    date     = db.Column(db.String(20),  nullable=False)
    time     = db.Column(db.String(20),  nullable=False)
    location = db.Column(db.String(100))
    mode     = db.Column(db.String(20))

class Note(db.Model):
    __tablename__ = 'notes'
    id           = db.Column(db.Integer, primary_key=True)
    group_id     = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    uploaded_by  = db.Column(db.Integer, db.ForeignKey('users.id'),  nullable=False)
    filename     = db.Column(db.String(200), nullable=False)
    original_name= db.Column(db.String(200))
    uploaded_at  = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    __tablename__ = 'messages'
    id       = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    user_id  = db.Column(db.Integer, db.ForeignKey('users.id'),  nullable=False)
    message  = db.Column(db.String(2000), nullable=False)
    timestamp= db.Column(db.DateTime, default=datetime.utcnow)


# ── Routes ───────────────────────────────────────

@app.route('/')
def home():
    return ok('Study Group Finder API is running.')

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json(silent=True)
    if not data:
        return err('Invalid JSON.', 400)
    name     = (data.get('name') or '').strip()
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not name or not email or not password:
        return err('All fields required.', 400)
    if len(password) < 8:
        return err('Password must be at least 8 characters.', 400)
    if User.query.filter_by(email=email).first():
        return err('Email already registered.', 409)
    hashed = bcrypt.generate_password_hash(password).decode('utf-8')
    db.session.add(User(name=name, email=email, password=hashed))
    db.session.commit()
    return ok('Account created.')

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True)
    if not data:
        return err('Invalid JSON.', 400)
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not email or not password:
        return err('Email and password required.', 400)
    user = User.query.filter_by(email=email).first()
    if not user or not bcrypt.check_password_hash(user.password, password):
        return err('Invalid email or password.', 401)
    session.clear()
    session['user_id'] = user.id
    session.permanent = True
    return ok('Login successful.', user_id=user.id, name=user.name)

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return ok('Logged out.')

@app.route('/me', methods=['GET'])
def me():
    if not is_logged_in():
        return err('Not authenticated.', 401)
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        return err('User not found.', 404)
    return jsonify({'user_id': user.id, 'name': user.name, 'email': user.email})

@app.route('/create-group', methods=['POST'])
def create_group():
    if not is_logged_in():
        return err('Login required.', 401)
    data = request.get_json(silent=True)
    if not data:
        return err('Invalid JSON.', 400)
    name = (data.get('name') or '').strip()
    if not name:
        return err('Group name required.', 400)
    description = (data.get('description') or '').strip()
    group = Group(name=name, description=description, created_by=session['user_id'])
    db.session.add(group)
    db.session.flush()
    db.session.add(GroupMember(user_id=session['user_id'], group_id=group.id))
    db.session.commit()
    return ok('Group created.', group_id=group.id)

@app.route('/groups', methods=['GET'])
def get_groups():
    groups = Group.query.all()
    result = []
    for g in groups:
        count = GroupMember.query.filter_by(group_id=g.id).count()
        result.append({
            'id': g.id,
            'name': g.name,
            'description': g.description or '',
            'member_count': count
        })
    return jsonify(result)

@app.route('/join-group', methods=['POST'])
def join_group():
    if not is_logged_in():
        return err('Login required.', 401)
    data = request.get_json(silent=True)
    group_id = data.get('group_id') if data else None
    if not group_id:
        return err('group_id required.', 400)
    if not db.session.get(Group, group_id):
        return err('Group not found.', 404)
    if GroupMember.query.filter_by(user_id=session['user_id'], group_id=group_id).first():
        return err('Already a member.', 409)
    db.session.add(GroupMember(user_id=session['user_id'], group_id=group_id))
    db.session.commit()
    return ok('Joined group.')

@app.route('/leave-group', methods=['POST'])
def leave_group():
    if not is_logged_in():
        return err('Login required.', 401)
    data = request.get_json(silent=True)
    group_id = data.get('group_id') if data else None
    if not group_id:
        return err('group_id required.', 400)
    deleted = GroupMember.query.filter_by(
        user_id=session['user_id'], group_id=group_id
    ).delete()
    db.session.commit()
    if not deleted:
        return err('Not a member.', 404)
    return ok('Left group.')

@app.route('/schedule-session', methods=['POST'])
def schedule_session():
    if not is_logged_in():
        return err('Login required.', 401)
    data = request.get_json(silent=True)
    if not data:
        return err('Invalid JSON.', 400)
    group_id = data.get('group_id')
    title    = (data.get('title') or '').strip()
    date     = (data.get('date') or '').strip()
    time     = (data.get('time') or '').strip()
    if not group_id or not title or not date or not time:
        return err('group_id, title, date, time required.', 400)
    if not db.session.get(Group, group_id):
        return err('Group not found.', 404)
    if not is_group_member(group_id):
        return err('Must be a group member.', 403)
    s = StudySession(
        group_id=group_id, title=title, date=date, time=time,
        location=(data.get('location') or '').strip(),
        mode=(data.get('mode') or '').strip()
    )
    db.session.add(s)
    db.session.commit()
    return ok('Session scheduled.', session_id=s.id)

@app.route('/sessions/<int:group_id>', methods=['GET'])
def get_sessions(group_id):
    if not db.session.get(Group, group_id):
        return err('Group not found.', 404)
    sessions = StudySession.query.filter_by(group_id=group_id).all()
    return jsonify([{
        'id': s.id, 'title': s.title, 'date': s.date,
        'time': s.time, 'location': s.location, 'mode': s.mode
    } for s in sessions])

@app.route('/upload-note', methods=['POST'])
def upload_note():
    if not is_logged_in():
        return err('Login required.', 401)
    file     = request.files.get('file')
    group_id = request.form.get('group_id', type=int)
    if not file or not file.filename:
        return err('No file provided.', 400)
    if not group_id:
        return err('group_id required.', 400)
    if not db.session.get(Group, group_id):
        return err('Group not found.', 404)
    if not is_group_member(group_id):
        return err('Must be a group member.', 403)
    if not allowed_file(file.filename):
        return err('File type not allowed.', 400)
    original_name = file.filename
    safe_name     = secure_filename(original_name)
    unique_name   = str(int(datetime.utcnow().timestamp())) + '_' + safe_name
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
    db.session.add(Note(
        group_id=group_id, uploaded_by=session['user_id'],
        filename=unique_name, original_name=original_name
    ))
    db.session.commit()
    return ok('File uploaded.')

@app.route('/notes/<int:group_id>', methods=['GET'])
def get_notes(group_id):
    if not db.session.get(Group, group_id):
        return err('Group not found.', 404)
    notes = Note.query.filter_by(group_id=group_id).all()
    return jsonify([{
        'id': n.id,
        'filename': n.original_name,
        'uploaded_at': n.uploaded_at.isoformat() if n.uploaded_at else None
    } for n in notes])


# ── WebSocket ────────────────────────────────────

@socketio.on('join')
def handle_join(data):
    group_id = data.get('group_id')
    if group_id:
        join_room(str(group_id))

@socketio.on('message')
def handle_message(data):
    group_id = data.get('group_id')
    user_id  = data.get('user_id')
    text     = (data.get('message') or '').strip()
    if not group_id or not user_id or not text:
        return
    if len(text) > 2000:
        text = text[:2000]
    msg = Message(group_id=group_id, user_id=user_id,
                  message=text, timestamp=datetime.utcnow())
    db.session.add(msg)
    db.session.commit()
    send({'group_id': group_id, 'user_id': user_id,
          'message': text, 'timestamp': msg.timestamp.isoformat()},
         room=str(group_id))


# ── Error handlers ───────────────────────────────

@app.errorhandler(413)
def too_large(e):
    return err('File too large. Max 10MB.', 413)

@app.errorhandler(404)
def not_found(e):
    return err('Not found.', 404)

@app.errorhandler(405)
def not_allowed(e):
    return err('Method not allowed.', 405)


# ── Run ──────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)