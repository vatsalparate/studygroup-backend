import eventlet
eventlet.monkey_patch()

import os
from datetime import datetime
from functools import wraps
import cloudinary
import cloudinary.uploader

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_socketio import SocketIO, send, join_room
from flask_cors import CORS
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, send_from_directory
import jwt as pyjwt

app = Flask(__name__)

cloudinary.config(
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key    = os.environ.get('CLOUDINARY_API_KEY'),
    api_secret = os.environ.get('CLOUDINARY_API_SECRET')
)

app.config['SECRET_KEY'] = 'studygroup_secret_key_2024_xk92'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///study.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'txt', 'md', 'docx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

ALLOWED_ORIGINS = [
    'http://127.0.0.1:5500',
    'http://localhost:5500',
    'https://studygroup-vatsal.netlify.app'
]

CORS(app,
     supports_credentials=True,
     origins=ALLOWED_ORIGINS,
     allow_headers=['Content-Type', 'Authorization'],
     methods=['GET', 'POST', 'OPTIONS'])

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ── JWT Helpers ───────────────────────────────────

def create_token(user_id):
    return pyjwt.encode(
        {'user_id': user_id},
        app.config['SECRET_KEY'],
        algorithm='HS256'
    )

def get_user_from_token():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[7:]
    try:
        data = pyjwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return data.get('user_id')
    except:
        return None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = get_user_from_token()
        if not user_id:
            return jsonify({'msg': 'Login required.'}), 401
        request.user_id = user_id
        return f(*args, **kwargs)
    return decorated


# ── Other Helpers ─────────────────────────────────

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_group_member(user_id, group_id):
    return GroupMember.query.filter_by(
        user_id=user_id, group_id=group_id
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
    id            = db.Column(db.Integer, primary_key=True)
    group_id      = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    uploaded_by   = db.Column(db.Integer, db.ForeignKey('users.id'),  nullable=False)
    filename      = db.Column(db.String(200), nullable=False)
    original_name = db.Column(db.String(200))
    uploaded_at   = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    __tablename__ = 'messages'
    id        = db.Column(db.Integer, primary_key=True)
    group_id  = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    user_id   = db.Column(db.Integer, db.ForeignKey('users.id'),  nullable=False)
    message   = db.Column(db.String(2000), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# Create all tables after models are defined
with app.app_context():
    db.create_all()


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
    token = create_token(user.id)
    return ok('Login successful.', token=token, user_id=user.id, name=user.name)

@app.route('/logout', methods=['POST'])
def logout():
    return ok('Logged out.')

@app.route('/me', methods=['GET'])
@login_required
def me():
    user = db.session.get(User, request.user_id)
    if not user:
        return err('User not found.', 404)
    return jsonify({'user_id': user.id, 'name': user.name, 'email': user.email})

@app.route('/create-group', methods=['POST'])
@login_required
def create_group():
    data = request.get_json(silent=True)
    if not data:
        return err('Invalid JSON.', 400)
    name = (data.get('name') or '').strip()
    if not name:
        return err('Group name required.', 400)
    description = (data.get('description') or '').strip()
    group = Group(name=name, description=description, created_by=request.user_id)
    db.session.add(group)
    db.session.flush()
    db.session.add(GroupMember(user_id=request.user_id, group_id=group.id))
    db.session.commit()
    return ok('Group created.', group_id=group.id)

@app.route('/groups', methods=['GET'])
def get_groups():
    try:
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
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/join-group', methods=['POST'])
@login_required
def join_group():
    data = request.get_json(silent=True)
    group_id = data.get('group_id') if data else None
    if not group_id:
        return err('group_id required.', 400)
    if not db.session.get(Group, group_id):
        return err('Group not found.', 404)
    if GroupMember.query.filter_by(user_id=request.user_id, group_id=group_id).first():
        return err('Already a member.', 409)
    db.session.add(GroupMember(user_id=request.user_id, group_id=group_id))
    db.session.commit()
    return ok('Joined group.')

@app.route('/leave-group', methods=['POST'])
@login_required
def leave_group():
    data = request.get_json(silent=True)
    group_id = data.get('group_id') if data else None
    if not group_id:
        return err('group_id required.', 400)
    deleted = GroupMember.query.filter_by(
        user_id=request.user_id, group_id=group_id
    ).delete()
    db.session.commit()
    if not deleted:
        return err('Not a member.', 404)
    return ok('Left group.')
@app.route('/delete-group/<int:group_id>', methods=['POST'])
@login_required
def delete_group(group_id):
    group = db.session.get(Group, group_id)
    if not group:
        return err('Group not found.', 404)
    if group.created_by != request.user_id:
        return err('Only the group creator can delete this group.', 403)
    db.session.delete(group)
    db.session.commit()
    return ok('Group deleted.')

@app.route('/schedule-session', methods=['POST'])
@login_required
def schedule_session():
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
    if not is_group_member(request.user_id, group_id):
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
@login_required
def upload_note():
    file     = request.files.get('file')
    group_id = request.form.get('group_id', type=int)
    if not file or not file.filename:
        return err('No file provided.', 400)
    if not group_id:
        return err('group_id required.', 400)
    if not db.session.get(Group, group_id):
        return err('Group not found.', 404)
    if not is_group_member(request.user_id, group_id):
        return err('Must be a group member.', 403)
    if not allowed_file(file.filename):
        return err('File type not allowed.', 400)

    # Upload to Cloudinary
    result = cloudinary.uploader.upload(
        file,
        resource_type='auto',
        folder='studygroup'
    )

    db.session.add(Note(
        group_id=group_id,
        uploaded_by=request.user_id,
        filename=result['secure_url'],
        original_name=file.filename
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
        'url': n.filename,
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
    socketio.run(app, host='0.0.0.0', port=5000, debug=True,use_reloader=False)