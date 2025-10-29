from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta
import hashlib
import json
import os
from functools import wraps
import re
import requests
from io import BytesIO
from PIL import Image

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'postgresql+psycopg://neondb_owner:npg_qkhLBC37TERv@ep-restless-credit-a127n0g1-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require'
)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_recycle': 300,
    'pool_pre_ping': True
}


app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'danger'
login_manager.session_protection = "strong"

# Supabase Configuration
SUPABASE_URL = "https://cudxtncwoyhenkogwejh.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN1ZHh0bmN3b3loZW5rb2d3ZWpoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MDUwNDEwNiwiZXhwIjoyMDc2MDgwMTA2fQ.REHcU6yKSf3I7FGgxujU4NXYrucVUTT07qvrwHIcJ4w"
SUPABASE_STORAGE_BUCKET = "images"

# Security headers
@app.after_request
def apply_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# Session validation middleware
@app.before_request
def before_request():
    if current_user.is_authenticated:
        if 'user_id' not in session or session['user_id'] != current_user.id:
            logout_user()
            session.clear()
            flash('🔒 Session expired. Please login again.', 'danger')
            return redirect(url_for('login'))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    blogs = db.relationship('BlogPost', backref='author', lazy=True)
    comments = db.relationship('Comment', backref='author', lazy=True)
    is_admin = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    last_login = db.Column(db.DateTime)
    # UPDATED: Only total image limit, no daily limit
    image_limit = db.Column(db.Integer, default=30)
    last_upload_date = db.Column(db.Date)

class BlogPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    comments = db.relationship('Comment', backref='blog', lazy=True, cascade='all, delete-orphan')
    # NEW: Image support for posts
    image_url = db.Column(db.String(500))
    is_image_post = db.Column(db.Boolean, default=False)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    blog_id = db.Column(db.Integer, db.ForeignKey('blog_post.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message_text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)
    # NEW: Image support for private messages
    image_url = db.Column(db.String(500))
    is_image_message = db.Column(db.Boolean, default=False)
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_messages')

class GroupMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message_text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    # NEW: Image support for group messages
    image_url = db.Column(db.String(500))
    is_image_message = db.Column(db.Boolean, default=False)
    sender = db.relationship('User', backref='group_messages')

# NEW: UserImage model for tracking uploaded images
class UserImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    image_url = db.Column(db.String(500), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    used_in_posts = db.Column(db.Boolean, default=False)
    used_in_chats = db.Column(db.Boolean, default=False)
    user = db.relationship('User', backref='uploaded_images')

class AdminSlider(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=True)
    content = db.Column(db.Text, nullable=True)
    image_path = db.Column(db.String(200), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    order_index = db.Column(db.Integer, default=0)

@login_manager.user_loader
def load_user(user_id):
    if 'user_id' in session and str(session['user_id']) == user_id:
        return User.query.get(int(user_id))
    return None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('🔒 Please login first', 'danger')
            return redirect(url_for('login'))
        
        user = User.query.get(current_user.id)
        if not user or not user.is_admin:
            flash('🚫 Admin access required. Unauthorized access detected.', 'danger')
            return redirect(url_for('home'))
        
        return f(*args, **kwargs)
    return decorated_function

# UPDATED: Image utility functions
def compress_image(image_file, max_size=(1080, 1080), quality=85):
    """Compress image to reduce file size"""
    try:
        img = Image.open(image_file)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        # Save to bytes with compression
        output = BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        output.seek(0)
        
        return output
    except Exception as e:
        print(f"Image compression error: {e}")
        return None

def upload_to_supabase(image_file, filename, user_id):
    """Upload image to Supabase Storage"""
    try:
        # Compress image first
        compressed_image = compress_image(image_file)
        if not compressed_image:
            return None
            
        # Prepare upload
        headers = {
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'image/jpeg'
        }
        
        # Create unique filename
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"user_{user_id}_{timestamp}_{filename}"
        
        # Upload to Supabase
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/{unique_filename}"
        response = requests.post(upload_url, headers=headers, data=compressed_image.read())
        
        if response.status_code == 200:
            # Get public URL
            public_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/{unique_filename}"
            return public_url
        else:
            print(f"Supabase upload error: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"Upload error: {e}")
        return None

def check_image_limits(user):
    """Check if user can upload more images - ONLY TOTAL LIMIT"""
    # Admins have no limits
    if user.is_admin:
        return True, "ok"
    
    # Count total images user has uploaded
    user_images_count = UserImage.query.filter_by(user_id=user.id).count()
    
    # Check total limit (30 images lifetime)
    if user_images_count >= (user.image_limit or 30):
        return False, "total"
    
    return True, "ok"

def update_image_usage(user):
    """Update user's last upload date"""
    user.last_upload_date = datetime.utcnow().date()
    db.session.commit()

def delete_oldest_images(user_id, count=1):
    """Delete oldest images when user reaches limit"""
    oldest_images = UserImage.query.filter_by(user_id=user_id).order_by(UserImage.created_at.asc()).limit(count).all()
    
    for image in oldest_images:
        # Delete from Supabase (optional - you can keep for cost savings)
        # For now, just delete from database
        db.session.delete(image)
    
    db.session.commit()

# Auto-delete old messages
def cleanup_old_messages():
    with app.app_context():
        try:
            group_cutoff = datetime.utcnow() - timedelta(hours=48)
            old_group_messages = GroupMessage.query.filter(GroupMessage.timestamp < group_cutoff).all()
            for msg in old_group_messages:
                db.session.delete(msg)
            
            private_cutoff = datetime.utcnow() - timedelta(days=90)
            old_private_messages = Message.query.filter(Message.timestamp < private_cutoff).all()
            for msg in old_private_messages:
                db.session.delete(msg)
            
            db.session.commit()
            if old_group_messages or old_private_messages:
                print(f"🧹 Cleaned up {len(old_group_messages)} group messages and {len(old_private_messages)} private messages")
        except Exception as e:
            print(f"Error cleaning up messages: {e}")

def get_unread_message_count(user_id):
    return Message.query.filter_by(receiver_id=user_id, read=False).count()

# Get latest chat time for each user
def get_latest_chat_time(user_id):
    """Get the latest message time for each chat partner"""
    latest_times = {}
    
    # Get messages where user is sender
    sent_messages = Message.query.filter_by(sender_id=user_id).all()
    for msg in sent_messages:
        if msg.receiver_id not in latest_times or msg.timestamp > latest_times[msg.receiver_id]:
            latest_times[msg.receiver_id] = msg.timestamp
    
    # Get messages where user is receiver
    received_messages = Message.query.filter_by(receiver_id=user_id).all()
    for msg in received_messages:
        if msg.sender_id not in latest_times or msg.timestamp > latest_times[msg.sender_id]:
            latest_times[msg.sender_id] = msg.timestamp
    
    return latest_times

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#007bff">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="google-site-verification" content="gXygyyT-W9A-Z8VgEcM2_S7Pjpb3zReemPU6_Gy2yMM" />

    <!-- 🧠 SEO Meta Tags -->
    <meta name="description" content="Tuition Area Network connects students to share notes, blogs, and learning resources. Join now to grow with knowledge and friends.">
    <meta name="keywords" content="tuition area network, students, education, learning, study platform, college, notes sharing, school network, student community, blogs, social learning, latur, latur maharashtra, tution area latur, tution area, fun social media, social network latur, motegaonkar, rcc latur, vaa latur, iib latur, tutions, satish pawar">
    <meta name="author" content="Tuition Area Network Team">
    <meta name="robots" content="index, follow">

    <title>📚 Tuition Area Network | Learn, Share & Connect</title>

    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/js/bootstrap.bundle.min.js"></script>

    <style>
        /* You can keep your custom CSS here */
    </style>
</head>

        :root {
            --primary: #007bff;
            --secondary: #6c757d;
            --success: #28a745;
            --danger: #dc3545;
            --warning: #ffc107;
            --info: #17a2b8;
            --light: #f8f9fa;
            --dark: #343a40;
        }
        
        * {
            -webkit-tap-highlight-color: transparent;
            -webkit-touch-callout: none;
            -webkit-user-select: none;
            -moz-user-select: none;
            -ms-user-select: none;
            user-select: none;
            box-sizing: border-box;
        }
        
        input, textarea {
            -webkit-user-select: text;
            -moz-user-select: text;
            -ms-user-select: text;
            user-select: text;
        }
        
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            min-height: 100vh;
            margin: 0;
            padding: 5px;
            padding-bottom: 70px;
        }
        
        .mobile-container {
            max-width: 100%;
            margin: 0 auto;
            background: white;
            min-height: 100vh;
            box-shadow: 0 0 20px rgba(0,0,0,0.1);
            position: relative;
        }
        
        .app-header {
            background: linear-gradient(135deg, #007bff, #0056b3);
            color: white;
            padding: 15px 0;
            position: sticky;
            top: 0;
            z-index: 1000;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        .app-title {
            font-size: 1.4rem;
            font-weight: 700;
            margin: 0;
        }
        
        .nav-icon {
            font-size: 1.2rem;
            padding: 8px 12px;
            border-radius: 50%;
            transition: all 0.3s ease;
        }
        
        .nav-icon:hover {
            background: rgba(255,255,255,0.2);
        }
        
        .content-area {
            padding: 20px 15px;
            min-height: calc(100vh - 140px);
        }
        
        .mobile-card {
            background: white;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            border: none;
            transition: all 0.3s ease;
            cursor: pointer;
        }
        
        .mobile-card:active {
            transform: scale(0.98);
        }
        
        .btn-mobile {
            padding: 16px 20px;
            border-radius: 12px;
            font-size: 1.1rem;
            font-weight: 600;
            border: none;
            transition: all 0.3s ease;
            width: 100%;
            margin: 8px 0;
        }
        
        .btn-mobile:active {
            transform: scale(0.95);
        }
        
        .btn-primary-mobile {
            background: linear-gradient(135deg, #007bff, #0056b3);
            color: white;
        }
        
        .btn-success-mobile {
            background: linear-gradient(135deg, #28a745, #1e7e34);
            color: white;
        }
        
        .btn-danger-mobile {
            background: linear-gradient(135deg, #dc3545, #c82333);
            color: white;
        }
        
        .btn-warning-mobile {
            background: linear-gradient(135deg, #ffc107, #e0a800);
            color: #212529;
        }
        
        .form-mobile {
            width: 100%;
        }
        
        .input-mobile {
            width: 100%;
            padding: 16px;
            border: 2px solid #e9ecef;
            border-radius: 12px;
            font-size: 1.1rem;
            margin: 8px 0;
            transition: all 0.3s ease;
            background: #f8f9fa;
        }
        
        .input-mobile:focus {
            border-color: #007bff;
            background: white;
            outline: none;
            box-shadow: 0 0 0 3px rgba(0,123,255,0.1);
        }
        
        .chat-container {
            height: 65vh;
            display: flex;
            flex-direction: column;
            background: #f8f9fa;
            border-radius: 16px;
            overflow: hidden;
        }
        
        .chat-header {
            background: linear-gradient(135deg, #007bff, #0056b3);
            color: white;
            padding: 15px;
            text-align: center;
            font-weight: 600;
        }
        
        .chat-messages {
            flex: 1;
            overflow-y: auto;
            padding: 15px;
            background: #f0f2f5;
        }
        
        .message {
            max-width: 85%;
            margin: 8px 0;
            padding: 12px 16px;
            border-radius: 18px;
            word-wrap: break-word;
            animation: messageSlide 0.3s ease;
        }
        
        @keyframes messageSlide {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .my-message {
            background: linear-gradient(135deg, #007bff, #0056b3);
            color: white;
            margin-left: auto;
            border-bottom-right-radius: 6px;
        }
        
        .their-message {
            background: white;
            color: #333;
            margin-right: auto;
            border-bottom-left-radius: 6px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        
        .group-message {
            background: white;
            color: #333;
            margin: 8px 0;
            border-radius: 12px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            max-width: 90%;
        }
        
        .message-sender {
            font-weight: 600;
            font-size: 0.9rem;
            margin-bottom: 4px;
            color: #007bff;
        }
        
        .message-time {
            font-size: 0.75rem;
            opacity: 0.7;
            margin-top: 4px;
        }
        
        .chat-input-container {
            background: white;
            padding: 15px;
            border-top: 1px solid #e9ecef;
            display: flex;
            gap: 10px;
            align-items: center;
        }
        
        .chat-input {
            flex: 1;
            padding: 12px 16px;
            border: 2px solid #e9ecef;
            border-radius: 25px;
            font-size: 1rem;
            background: #f8f9fa;
        }
        
        .send-btn {
            background: #007bff;
            color: white;
            border: none;
            width: 45px;
            height: 45px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.2rem;
            transition: all 0.3s ease;
        }
        
        .send-btn:active {
            background: #0056b3;
            transform: scale(0.9);
        }
        
        .blog-card {
            background: white;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            border-left: 5px solid #007bff;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .blog-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0,0,0,0.15);
        }
        
        .blog-title {
            font-size: 1.3rem;
            font-weight: 700;
            color: #333;
            margin-bottom: 10px;
        }
        
        .blog-content {
            color: #666;
            line-height: 1.5;
            margin-bottom: 15px;
        }
        
        .blog-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.9rem;
            color: #999;
        }
        
        .blog-author {
            color: #007bff;
            font-weight: 600;
            text-decoration: none;
        }
        
        .blog-author:hover {
            text-decoration: underline;
        }
        
        .comment-section {
            margin-top: 20px;
            border-top: 1px solid #e9ecef;
            padding-top: 15px;
        }
        
        .comment-card {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 12px 15px;
            margin-bottom: 10px;
            border-left: 3px solid #007bff;
        }
        
        .comment-author {
            font-weight: 600;
            color: #007bff;
            font-size: 0.9rem;
        }
        
        .comment-content {
            margin: 5px 0;
            color: #333;
        }
        
        .comment-time {
            font-size: 0.75rem;
            color: #999;
        }
        
        .alert-mobile {
            padding: 15px;
            border-radius: 12px;
            margin: 10px 0;
            font-weight: 500;
            border: none;
        }
        
        .bottom-nav {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: white;
            padding: 10px 0;
            box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-around;
            z-index: 1000;
        }
        
        .nav-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            text-decoration: none;
            color: #666;
            font-size: 0.8rem;
            padding: 8px 12px;
            border-radius: 12px;
            transition: all 0.3s ease;
        }
        
        .nav-item.active {
            color: #007bff;
            background: rgba(0,123,255,0.1);
        }
        
        .nav-icon {
            font-size: 1.2rem;
            margin-bottom: 4px;
        }
        
        .profile-header {
            text-align: center;
            padding: 20px 0;
            background: linear-gradient(135deg, #007bff, #0056b3);
            color: white;
            border-radius: 16px;
            margin-bottom: 20px;
        }
        
        .profile-avatar {
            width: 80px;
            height: 80px;
            background: rgba(255,255,255,0.2);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2rem;
            margin: 0 auto 15px;
        }
        
        .user-card {
            display: flex;
            align-items: center;
            padding: 15px;
            background: white;
            border-radius: 12px;
            margin-bottom: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
        }
        
        .user-card:active {
            transform: scale(0.98);
        }
        
        .user-avatar {
            width: 50px;
            height: 50px;
            background: linear-gradient(135deg, #007bff, #0056b3);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
            font-size: 1.2rem;
            margin-right: 15px;
        }
        
        .user-info {
            flex: 1;
        }
        
        .user-name {
            font-weight: 600;
            color: #333;
            margin-bottom: 5px;
        }
        
        .user-stats {
            font-size: 0.8rem;
            color: #666;
        }
        
        .admin-badge {
            background: linear-gradient(135deg, #ffc107, #e0a800);
            color: #212529;
            padding: 4px 8px;
            border-radius: 8px;
            font-size: 0.7rem;
            font-weight: bold;
        }
        
        .banned-badge {
            background: linear-gradient(135deg, #dc3545, #c82333);
            color: white;
            padding: 4px 8px;
            border-radius: 8px;
            font-size: 0.7rem;
            font-weight: bold;
        }
        
        .search-container {
            margin-bottom: 20px;
        }
        
        .search-input {
            width: 100%;
            padding: 15px;
            border: 2px solid #e9ecef;
            border-radius: 12px;
            font-size: 1rem;
            background: #f8f9fa;
            transition: all 0.3s ease;
        }
        
        .search-input:focus {
            border-color: #007bff;
            background: white;
            outline: none;
            box-shadow: 0 0 0 3px rgba(0,123,255,0.1);
        }
        
        /* FIXED: SLIDER IN NORMAL FLOW - NOT STICKY */
        .admin-slider-container {
            margin-bottom: 20px;
            position: relative;
        }
        
        .admin-slider {
            height: 140px;
            overflow: hidden;
            position: relative;
            border-radius: 16px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            border: 3px solid #fff;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            cursor: pointer;
        }
        
        .slider-track {
            display: flex;
            transition: transform 0.5s ease;
            height: 100%;
        }
        
        .slider-slide {
            min-width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            background: linear-gradient(135deg, rgba(255,255,255,0.95), rgba(255,255,255,0.85));
            color: #333;
            text-align: center;
            position: relative;
            border-radius: 13px;
        }
        
        .slider-slide img {
            max-height: 90px;
            max-width: 90px;
            border-radius: 12px;
            margin-right: 20px;
            cursor: pointer;
            transition: transform 0.3s ease;
            border: 3px solid #007bff;
            box-shadow: 0 4px 15px rgba(0,123,255,0.3);
        }
        
        .slider-slide img:hover {
            transform: scale(1.08);
            border-color: #0056b3;
        }
        
        .slider-content {
            flex: 1;
            cursor: pointer;
        }
        
        .slider-title {
            font-weight: bold;
            font-size: 1.3rem;
            margin-bottom: 8px;
            color: #007bff;
            text-shadow: 1px 1px 2px rgba(255,255,255,0.8);
        }
        
        .slider-text {
            font-size: 1rem;
            color: #555;
            font-weight: 500;
            max-height: 40px;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        .slider-controls {
            position: absolute;
            top: 50%;
            width: 100%;
            display: flex;
            justify-content: space-between;
            transform: translateY(-50%);
            padding: 0 15px;
            pointer-events: none;
        }
        
        .slider-btn {
            background: rgba(0,123,255,0.8);
            color: white;
            border: none;
            width: 35px;
            height: 35px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            pointer-events: all;
            transition: all 0.3s ease;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }
        
        .slider-btn:hover {
            background: rgba(0,123,255,1);
            transform: scale(1.1);
        }
        
        .slider-dots {
            position: absolute;
            bottom: 10px;
            left: 0;
            right: 0;
            display: flex;
            justify-content: center;
            gap: 8px;
        }
        
        .slider-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: rgba(0,123,255,0.5);
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .slider-dot.active {
            background: #007bff;
            transform: scale(1.2);
        }
        
        /* Image Modal */
        .image-modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.9);
            z-index: 2000;
            justify-content: center;
            align-items: center;
        }
        
        .modal-image {
            max-width: 90%;
            max-height: 90%;
            border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }
        
        .close-modal {
            position: absolute;
            top: 20px;
            right: 30px;
            color: white;
            font-size: 2rem;
            cursor: pointer;
            background: rgba(0,0,0,0.5);
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        /* Image in posts and messages */
        .image-in-post {
            max-width: 100%;
            border-radius: 12px;
            margin: 10px 0;
            cursor: pointer;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            border: 2px solid #e9ecef;
        }
        
        .image-message {
            max-width: 200px;
            border-radius: 12px;
            margin: 5px 0;
            cursor: pointer;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            border: 2px solid #e9ecef;
        }
        
        /* NEW: Terms and Conditions Modal */
        .terms-modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.8);
            z-index: 3000;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .terms-content {
            background: white;
            border-radius: 16px;
            padding: 25px;
            max-width: 90%;
            max-height: 80vh;
            overflow-y: auto;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }
        
        .terms-title {
            font-size: 1.5rem;
            font-weight: bold;
            color: #007bff;
            margin-bottom: 20px;
            text-align: center;
        }
        
        .terms-text {
            font-size: 0.9rem;
            line-height: 1.6;
            color: #333;
            margin-bottom: 20px;
        }
        
        .close-terms {
            background: #007bff;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            transition: all 0.3s ease;
        }
        
        .close-terms:hover {
            background: #0056b3;
        }
        
        /* NEW: Terms Checkbox Styles */
        .terms-checkbox {
            display: flex;
            align-items: center;
            margin: 15px 0;
            padding: 12px;
            background: #f8f9fa;
            border-radius: 8px;
            border: 2px solid #e9ecef;
        }
        
        .terms-checkbox input {
            margin-right: 10px;
            transform: scale(1.2);
        }
        
        .terms-checkbox label {
            font-size: 0.9rem;
            color: #333;
            cursor: pointer;
        }
        
        .terms-link {
            color: #007bff;
            text-decoration: none;
            font-size: 0.8rem;
            margin-left: 5px;
        }
        
        .terms-link:hover {
            text-decoration: underline;
        }
        
        /* NEW: Blog Detail Modal */
        .blog-modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.9);
            z-index: 2000;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .blog-modal-content {
            background: white;
            border-radius: 16px;
            padding: 25px;
            max-width: 90%;
            max-height: 85vh;
            overflow-y: auto;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            position: relative;
        }
        
        .close-blog-modal {
            position: absolute;
            top: 15px;
            right: 15px;
            background: #dc3545;
            color: white;
            border: none;
            width: 35px;
            height: 35px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 1.2rem;
        }
        
        .blog-modal-title {
            font-size: 1.5rem;
            font-weight: bold;
            color: #333;
            margin-bottom: 15px;
            padding-right: 40px;
        }
        
        .blog-modal-body {
            font-size: 1rem;
            line-height: 1.6;
            color: #555;
            margin-bottom: 20px;
        }
        
        .blog-modal-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.9rem;
            color: #999;
            border-top: 1px solid #e9ecef;
            padding-top: 15px;
        }
        
        @media (max-width: 576px) {
            .content-area {
                padding: 15px 10px;
            }
            
            .mobile-card {
                padding: 15px;
            }
            
            .btn-mobile {
                padding: 14px 16px;
                font-size: 1rem;
            }
            
            .chat-container {
                height: 60vh;
            }
            
            .admin-slider {
                height: 120px;
            }
            
            .slider-title {
                font-size: 1.1rem;
            }
            
            .slider-text {
                font-size: 0.9rem;
            }
            
            .slider-slide img {
                max-height: 70px;
                max-width: 70px;
            }
            
            .terms-content {
                padding: 20px;
            }
            
            .blog-modal-content {
                padding: 20px;
            }
        }
        
        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid #f3f3f3;
            border-top: 3px solid #007bff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .credentials-table {
            width: 100%;
            font-size: 0.85rem;
        }
        
        .credentials-table th {
            background: #f8f9fa;
            padding: 10px;
            text-align: left;
            border-bottom: 2px solid #dee2e6;
        }
        
        .credentials-table td {
            padding: 10px;
            border-bottom: 1px solid #dee2e6;
            cursor: pointer;
            transition: background-color 0.2s ease;
        }
        
        .credentials-table td:hover {
            background-color: #f8f9fa;
        }
        
        .copy-credential {
            background: #007bff;
            color: white;
            border: none;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.7rem;
            cursor: pointer;
            margin-left: 5px;
        }
        
        .copy-credential:hover {
            background: #0056b3;
        }
        
        .credential-field {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        
        .credential-text {
            flex: 1;
            font-family: 'Courier New', monospace;
        }
        
        .chat-time {
            font-size: 0.7rem;
            color: #999;
            margin-top: 2px;
        }
        
        .chat-preview {
            font-size: 0.8rem;
            color: #666;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 200px;
        }
        
        /* NEW: Sticky Header */
        .sticky-header {
            position: sticky;
            top: 0;
            z-index: 1000;
            background: linear-gradient(135deg, #007bff, #0056b3);
            color: white;
            padding: 15px 0;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
        }
    </style>
</head>
<body>
    <div class="mobile-container">
        <!-- ONLY SHOW HEADER FOR LOGGED-IN USERS -->
        {% if current_user.is_authenticated %}
        <div class="sticky-header">
            <div class="container">
                <div class="d-flex justify-content-between align-items-center">
                    <h1 class="app-title">📚 Tuition Area Network</h1>
                    <div class="d-flex gap-2">
                        {% if current_user.is_admin %}
                        <a href="/admin" class="nav-icon text-white">
                            <i class="fas fa-crown"></i>
                        </a>
                        {% endif %}
                        <a href="/new_blog" class="nav-icon text-white">
                            <i class="fas fa-plus"></i>
                        </a>
                        <a href="/users" class="nav-icon text-white">
                            <i class="fas fa-users"></i>
                        </a>
                        <a href="/private_chats" class="nav-icon text-white">
                            <i class="fas fa-comment-dots"></i>
                        </a>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}

        <div class="content-area">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                    <div class="alert-mobile alert-{{ 'danger' if category == 'error' else category }}">
                        {{ message }}
                    </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            
            <!-- FIXED: SLIDER ONLY SHOWS ON HOME PAGE -->
            {% if current_user.is_authenticated and admin_slides and request.path == '/' %}
            <div class="admin-slider-container">
                <div class="admin-slider" onclick="openSliderFullView()">
                    <div class="slider-track" id="sliderTrack">
                        {% for slide in admin_slides %}
                        <div class="slider-slide">
                            {% if slide.image_path %}
                            <img src="{{ url_for('static', filename=slide.image_path) }}" 
                                 alt="{{ slide.title }}" 
                                 onclick="event.stopPropagation(); openImageModal('{{ url_for('static', filename=slide.image_path) }}')">
                            {% endif %}
                            <div class="slider-content" onclick="openSliderFullView()">
                                {% if slide.title %}<div class="slider-title">{{ slide.title }}</div>{% endif %}
                                {% if slide.content %}<div class="slider-text">{{ slide.content }}</div>{% endif %}
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                    {% if admin_slides|length > 1 %}
                    <div class="slider-controls">
                        <button class="slider-btn" onclick="event.stopPropagation(); prevSlide()">❮</button>
                        <button class="slider-btn" onclick="event.stopPropagation(); nextSlide()">❯</button>
                    </div>
                    <div class="slider-dots" id="sliderDots">
                        {% for i in range(admin_slides|length) %}
                        <div class="slider-dot {% if i == 0 %}active{% endif %}" onclick="event.stopPropagation(); goToSlide({{ i }})"></div>
                        {% endfor %}
                    </div>
                    {% endif %}
                </div>
            </div>
            {% endif %}

            <!-- Image Modal -->
            <div class="image-modal" id="imageModal">
                <span class="close-modal" onclick="closeImageModal()">&times;</span>
                <img class="modal-image" id="modalImage" src="" alt="Enlarged view">
            </div>
            
            <!-- Terms and Conditions Modal -->
            <div class="terms-modal" id="termsModal">
                <div class="terms-content">
                    <div class="terms-title">📜 Terms & Conditions</div>
                    <div class="terms-text">
                        All members must treat each other respectfully and avoid personal attacks. Content shared must comply with local laws and educational standards. Users should report technical issues or abuse via the designated support channels. Sharing sexually explicit or pornographic material is strictly prohibited. Child sexual abuse material will result in immediate account suspension and legal reporting. Threats of violence or harm toward any person are not tolerated. Personal login information should never be shared with others. Attempts to access another user's account without permission are strictly prohibited. Promoting cheating or academic dishonesty is not allowed. Posts containing illegal material,pirated content, or copyrighted work without authorization will be removed. Commercial promotions or advertisements must be approved by site administrators. Repeated posting of identical or irrelevant content may result in temporary suspension. Uploading files with malware,viruses, or malicious scripts is strictly prohibited. Users must not impersonate other members,site staff, or educational institutions. Content that incites hatred,discrimination, or harassment will be removed. Sharing private information of others without consent is forbidden. Posts containing illegal drugs,weapons, or explosives are not permitted. Automated scraping,bots, or attempts to disrupt the service are prohibited. Posts or messages encouraging self-harm,suicide, or harmful behavior will be removed. Content that misleads or spreads false information may be removed. Harassment,stalking, or any threatening behavior is strictly prohibited. Group or forum content must adhere to the same rules as personal posts. Exploitative content,scams, or phishing attempts will be removed. Content glorifying violence or illegal activity is not allowed. Users must not use the platform for unlawful or unauthorized commercial purposes. Posts should reflect the educational purpose of the site. Users are responsible for consequences arising from sharing prohibited material. Users are expected to engage constructively and avoid disruptive behavior. Users are prohibited from attempting to circumvent security measures or moderation systems. All posts,comments, and shared files should maintain community standards and respect for others. Users should report technical issues or abuse via the designated support channels. Continued violation of rules can lead to permanent account termination. Users must not manipulate system data,timestamps, or metadata to mislead administrators. False or misleading content designed to deceive other users is prohibited. Users must not impersonate public officials or educational authorities. Posting revenge porn,non-consensual intimate content, or private ID documents is strictly prohibited. Content that sexualizes minors in any form will result in immediate account suspension. Hateful memes or demeaning jokes about protected groups are not allowed. Repeated violations may result in account suspension or permanent ban. Admins may monitor posts,comments, and chats to ensure safety and compliance with site rules. Admins can review account metadata and activity logs to investigate violations. Admins may remove or edit posts and comments that violate these rules. Admins have the authority to restrict features or suspend accounts of users violating rules. Admins may require verification or additional information in cases of suspicious activity. Admins will only access sensitive data for moderation,safety, and legal compliance; passwords are never visible. Admins may archive messages or posts if required for safety,legal, or compliance reasons. Admins'urgent safety decisions take precedence; users may appeal afterward. Admins may limit visibility of content while reviewing serious complaints. Admins may contact users to clarify actions or gather information during investigations. Admins may implement temporary restrictions to prevent further rule violations. Admins will follow legal requirements for reporting unlawful activity. Admins may enforce rules in urgent cases to prevent harm or violations. Admins may contact users for clarification during investigations. Admins may require ID verification for appeals or contested bans when necessary. Admins can limit access to features or visibility of content while reviewing serious complaints. Admins may archive evidence and preserve logs for legal or safety reasons. Admins may restrict group membership or forum access if rules are broken. Admins may remove posts that promote extremist or illegal content. Admins may suspend or ban users who repeatedly violate rules. Admins may review reported content and decide enforcement actions. Admins have the discretion to enforce rules in urgent cases to prevent harm or violations. Admins may implement temporary restrictions to prevent further rule violations. Admins will keep sensitive personal data access limited to authorized staff only. Admins may contact users to gather additional information during investigations. Admins can require verification or additional information in cases of suspicious activity. Admins will maintain logs of all moderation actions for accountability. Admins may limit access to features or visibility of content while reviewing serious complaints. Users must not manipulate or exploit system vulnerabilities. Users must not encourage or glorify violence or illegal activity. Users must not post private chat screenshots without consent. Users must not share content that misleads or spreads false information. Users must not engage in harassment or threatening behavior. Users are responsible for their own content and any consequences arising from sharing prohibited material. Users must not create multiple accounts to evade bans. Users must not sell or trade other users'data. Users must not participate in organized harassment campaigns. Users must not post forged or fake documents. Users must not post promotional content without permission. Users must not impersonate victims to solicit sympathy or money. Users must not post or request sexually explicit images of anyone without consent. Users must not post content that violates the laws of India or local regulations. Users must not engage in offline harassment or stalking. Users must not manipulate timestamps or metadata to mislead administrators. Users must not join or promote extremist organizations. Users must not solicit illegal activities from other users. Users must not bypass account security or two-factor authentication. Users must not create spam accounts or bot-driven profiles. Users must not attempt to bribe moderators or admins. Users must not post content intended solely to provoke or derail discussions. Users must not share exam leaks,paid subscription content, or stolen materials. Users must not participate in political campaigns or harassment without permission. Users must cooperate with admins during investigations if requested. Users must maintain constructive and safe engagement within the community. Users must not circumvent moderation or safety measures.
                    </div>
                    <button class="close-terms" onclick="closeTermsModal()">I Understand</button>
                </div>
            </div>
            
            <!-- Blog Detail Modal -->
            <div class="blog-modal" id="blogModal">
                <div class="blog-modal-content">
                    <button class="close-blog-modal" onclick="closeBlogModal()">&times;</button>
                    <div class="blog-modal-title" id="blogModalTitle"></div>
                    <div class="blog-modal-body" id="blogModalContent"></div>
                    <div class="blog-modal-meta">
                        <div id="blogModalAuthor"></div>
                        <div id="blogModalDate"></div>
                    </div>
                    <div class="mt-3">
                        <a href="#" class="btn btn-primary" id="blogModalLink">View Full Post with Comments</a>
                    </div>
                </div>
            </div>
            
            {{ content|safe }}
        </div>

        <!-- ONLY SHOW BOTTOM NAV FOR LOGGED-IN USERS -->
        {% if current_user.is_authenticated %}
        <div class="bottom-nav">
            <a href="/" class="nav-item {{ 'active' if request.path == '/' }}">
                <i class="fas fa-home nav-icon"></i>
                <span>Home</span>
            </a>
            <a href="/new_blog" class="nav-item {{ 'active' if request.path == '/new_blog' }}">
                <i class="fas fa-edit nav-icon"></i>
                <span>Write</span>
            </a>
            <a href="/group_chat" class="nav-item {{ 'active' if request.path == '/group_chat' }}">
                <i class="fas fa-comments nav-icon"></i>
                <span>Group Chat</span>
            </a>
            <a href="/private_chats" class="nav-item {{ 'active' if request.path == '/private_chats' }}">
                <i class="fas fa-comment-dots nav-icon"></i>
                <span>Messages</span>
            </a>
            <a href="/profile" class="nav-item {{ 'active' if request.path == '/profile' }}">
                <i class="fas fa-user nav-icon"></i>
                <span>Profile</span>
            </a>
        </div>
        {% endif %}
    </div>

    <script>
        // Admin Slider Functionality
        let currentSlide = 0;
        const slides = document.querySelectorAll('.slider-slide');
        const totalSlides = slides.length;
        const track = document.getElementById('sliderTrack');
        const dots = document.querySelectorAll('.slider-dot');

        function updateSlider() {
            if (track) {
                track.style.transform = `translateX(-${currentSlide * 100}%)`;
                dots.forEach((dot, index) => {
                    dot.classList.toggle('active', index === currentSlide);
                });
            }
        }

        function nextSlide() {
            currentSlide = (currentSlide + 1) % totalSlides;
            updateSlider();
        }

        function prevSlide() {
            currentSlide = (currentSlide - 1 + totalSlides) % totalSlides;
            updateSlider();
        }

        function goToSlide(index) {
            currentSlide = index;
            updateSlider();
        }

        // Auto-advance slides every 5 seconds
        if (totalSlides > 1) {
            setInterval(nextSlide, 5000);
        }

        // Touch swipe for mobile
        let startX = 0;
        if (track) {
            track.addEventListener('touchstart', (e) => {
                startX = e.touches[0].clientX;
            });

            track.addEventListener('touchend', (e) => {
                const endX = e.changedTouches[0].clientX;
                const diff = startX - endX;
                
                if (Math.abs(diff) > 50) { // Minimum swipe distance
                    if (diff > 0) {
                        nextSlide();
                    } else {
                        prevSlide();
                    }
                }
            });
        }

        // Image Modal Functions
        function openImageModal(imageSrc) {
            const modal = document.getElementById('imageModal');
            const modalImage = document.getElementById('modalImage');
            modalImage.src = imageSrc;
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        }

        function closeImageModal() {
            const modal = document.getElementById('imageModal');
            modal.style.display = 'none';
            document.body.style.overflow = 'auto';
        }

        // NEW: Terms and Conditions Modal Functions
        function openTermsModal() {
            const modal = document.getElementById('termsModal');
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        }

        function closeTermsModal() {
            const modal = document.getElementById('termsModal');
            modal.style.display = 'none';
            document.body.style.overflow = 'auto';
        }

        // NEW: Blog Modal Functions
        function openBlogModal(blogId, title, content, author, date) {
            const modal = document.getElementById('blogModal');
            document.getElementById('blogModalTitle').textContent = title;
            document.getElementById('blogModalContent').textContent = content;
            document.getElementById('blogModalAuthor').textContent = 'By: ' + author;
            document.getElementById('blogModalDate').textContent = 'Posted: ' + date;
            document.getElementById('blogModalLink').href = '/blog/' + blogId;
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        }

        function closeBlogModal() {
            const modal = document.getElementById('blogModal');
            modal.style.display = 'none';
            document.body.style.overflow = 'auto';
        }

        // NEW: Slider Full View Function
        function openSliderFullView() {
            const slides = document.querySelectorAll('.slider-slide');
            const currentSlideContent = slides[currentSlide];
            const title = currentSlideContent.querySelector('.slider-title')?.textContent || '';
            const content = currentSlideContent.querySelector('.slider-text')?.textContent || '';
            
            if (title || content) {
                const modal = document.getElementById('blogModal');
                document.getElementById('blogModalTitle').textContent = title || 'Admin Announcement';
                document.getElementById('blogModalContent').textContent = content || 'No content available.';
                document.getElementById('blogModalAuthor').textContent = 'By: Admin';
                document.getElementById('blogModalDate').textContent = 'Posted: Recently';
                document.getElementById('blogModalLink').style.display = 'none';
                modal.style.display = 'flex';
                document.body.style.overflow = 'hidden';
            }
        }

        // Close modal when clicking outside the image
        document.getElementById('imageModal').addEventListener('click', function(e) {
            if (e.target === this) {
                closeImageModal();
            }
        });

        document.getElementById('termsModal').addEventListener('click', function(e) {
            if (e.target === this) {
                closeTermsModal();
            }
        });

        document.getElementById('blogModal').addEventListener('click', function(e) {
            if (e.target === this) {
                closeBlogModal();
            }
        });

        // Copy credential function
        function copyCredential(text, type) {
            navigator.clipboard.writeText(text).then(function() {
                // Show temporary notification
                const notification = document.createElement('div');
                notification.style.cssText = `
                    position: fixed;
                    top: 50%;
                    left: 50%;
                    transform: translate(-50%, -50%);
                    background: rgba(0,0,0,0.8);
                    color: white;
                    padding: 10px 20px;
                    border-radius: 8px;
                    z-index: 10000;
                    font-size: 0.9rem;
                `;
                notification.textContent = `✅ ${type} copied to clipboard!`;
                document.body.appendChild(notification);
                
                setTimeout(() => {
                    document.body.removeChild(notification);
                }, 2000);
            }).catch(function(err) {
                console.error('Failed to copy: ', err);
                alert('Failed to copy text');
            });
        }

        // NEW: Blog card click handlers
        document.addEventListener('DOMContentLoaded', function() {
            // Add click handlers to blog cards
            const blogCards = document.querySelectorAll('.blog-card');
            blogCards.forEach(card => {
                card.addEventListener('click', function(e) {
                    // Don't trigger if clicking on links or buttons
                    if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON' || e.target.closest('a') || e.target.closest('button')) {
                        return;
                    }
                    
                    const title = this.querySelector('.blog-title')?.textContent;
                    const content = this.querySelector('.blog-content')?.textContent;
                    const author = this.querySelector('.blog-author')?.textContent;
                    const date = this.querySelector('.text-muted')?.textContent;
                    const blogId = this.closest('[data-blog-id]')?.getAttribute('data-blog-id') || 
                                  this.querySelector('a[href*="/blog/"]')?.href.split('/').pop();
                    
                    if (title && content && blogId) {
                        openBlogModal(blogId, title, content, author || 'Unknown', date || 'Unknown date');
                    }
                });
            });
        });

        document.addEventListener('touchstart', function(){}, {passive: true});
        
        window.addEventListener('load', function() {
            setTimeout(function() {
                window.scrollTo(0, 1);
            }, 0);
        });
        
        let lastTouchEnd = 0;
        document.addEventListener('touchend', function (event) {
            const now = (new Date()).getTime();
            if (now - lastTouchEnd <= 300) {
                event.preventDefault();
            }
            lastTouchEnd = now;
        }, false);
    </script>
</body>
</html>
"""

LOGIN_TEMPLATE = """
<div class="d-flex justify-content-center align-items-center" style="min-height: 70vh;">
    <div class="mobile-card" style="max-width: 400px; width: 100%;">
        <div class="text-center mb-4">
            <div style="font-size: 3rem; margin-bottom: 1rem;">🔐</div>
            <h2 class="fw-bold">Welcome Back</h2>
            <p class="text-muted">Sign in with your email</p>
        </div>
        
        <form method="POST" class="form-mobile" id="loginForm">
            <input type="email" name="login" class="input-mobile" placeholder="📧 Email Address" required>
            <input type="password" name="password" class="input-mobile" placeholder="🔒 Password" required>
            
            <!-- NEW: Terms and Conditions Checkbox -->
            <div class="terms-checkbox">
                <input type="checkbox" id="agreeTerms" name="agree_terms" required>
                <label for="agreeTerms">
                    I agree to Terms & Conditions
                    <a href="javascript:void(0)" class="terms-link" onclick="openTermsModal()">View Terms & Conditions</a>
                </label>
            </div>
            
            <button type="submit" class="btn-mobile btn-primary-mobile" id="loginButton">
                <i class="fas fa-sign-in-alt me-2"></i>Sign In
            </button>
        </form>
        
        <div class="text-center mt-3">
            <p class="text-muted">Don't have an account? 
                <a href="/register" class="text-primary text-decoration-none fw-bold">Sign up here</a>
            </p>
        </div>
    </div>
</div>

<script>
// NEW: Form validation for terms agreement
document.getElementById('loginForm').addEventListener('submit', function(e) {
    const termsCheckbox = document.getElementById('agreeTerms');
    if (!termsCheckbox.checked) {
        e.preventDefault();
        alert('Please agree to the Terms & Conditions to continue.');
        return false;
    }
    return true;
});
</script>
"""

REGISTER_TEMPLATE = """
<div class="d-flex justify-content-center align-items-center" style="min-height: 70vh;">
    <div class="mobile-card" style="max-width: 400px; width: 100%;">
        <div class="text-center mb-4">
            <div style="font-size: 3rem; margin-bottom: 1rem;">🎉</div>
            <h2 class="fw-bold">Join Our Community</h2>
            <p class="text-muted">Create your account</p>
        </div>
        
        <form method="POST" class="form-mobile" id="registerForm">
            <input type="text" name="username" class="input-mobile" placeholder="👤 Username" required>
            <input type="email" name="email" class="input-mobile" placeholder="📧 Email Address" required>
            <input type="password" name="password" class="input-mobile" placeholder="🔒 Password" required>
            
            <!-- NEW: Terms and Conditions Checkbox -->
            <div class="terms-checkbox">
                <input type="checkbox" id="agreeTermsRegister" name="agree_terms" required>
                <label for="agreeTermsRegister">
                    I agree to Terms & Conditions
                    <a href="javascript:void(0)" class="terms-link" onclick="openTermsModal()">View Terms & Conditions</a>
                </label>
            </div>
            
            <button type="submit" class="btn-mobile btn-success-mobile">
                <i class="fas fa-user-plus me-2"></i>Create Account
            </button>
        </form>
        
        <div class="text-center mt-3">
            <p class="text-muted">Already have an account? 
                <a href="/login" class="text-primary text-decoration-none fw-bold">Sign in here</a>
            </p>
        </div>
    </div>
</div>

<script>
// NEW: Form validation for terms agreement
document.getElementById('registerForm').addEventListener('submit', function(e) {
    const termsCheckbox = document.getElementById('agreeTermsRegister');
    if (!termsCheckbox.checked) {
        e.preventDefault();
        alert('Please agree to the Terms & Conditions to continue.');
        return false;
    }
    return true;
});
</script>
"""

NEW_BLOG_TEMPLATE = """
<div class="mobile-card">
    <div class="text-center mb-4">
        <div style="font-size: 2.5rem;">📝</div>
        <h2 class="fw-bold">New Post</h2>
        <p class="text-muted">Share your thoughts with the community</p>
    </div>
    
    <form method="POST" enctype="multipart/form-data">
        <input type="text" name="title" class="input-mobile" placeholder="Post Title" required>
        <textarea name="content" class="input-mobile" placeholder="Write your amazing story here..." 
                  rows="6" style="resize: vertical;" required></textarea>
        
        <!-- Image Upload Field -->
        <div class="mb-3">
            <label for="image" class="form-label">Add Image (Optional)</label>
            <input type="file" name="image" class="input-mobile" accept="image/*" id="image">
            <div class="form-text">
                Maximum 30 images total. Currently used: {{ current_user.uploaded_images|length }}/30
                {% if current_user.uploaded_images|length >= 30 %}
                <br><strong>Storage full! Old images will be deleted automatically.</strong>
                {% endif %}
            </div>
        </div>
        
        <div class="d-grid gap-2 mt-4">
            <button type="submit" class="btn-mobile btn-success-mobile">
                Publish Post
            </button>
            <a href="/" class="btn-mobile" style="background: #6c757d; color: white;">
                Back to Feed
            </a>
        </div>
    </form>
</div>
"""

HOME_TEMPLATE = """
<div class="mb-4">
    <h2 class="fw-bold mb-3">Latest Posts</h2>
    
    {% if blogs %}
    <div class="blog-list">
        {% for blog in blogs %}
        <div class="blog-card" data-blog-id="{{ blog.id }}">
            <div class="blog-title">{{ blog.title }}</div>
            {% if blog.image_url %}
            <img src="{{ blog.image_url }}" alt="Post image" class="image-in-post" onclick="openImageModal('{{ blog.image_url }}')">
            {% endif %}
            <div class="blog-content">{{ blog.content[:150] }}{% if blog.content|length > 150 %}...{% endif %}</div>
            <div class="blog-meta">
                <div>
                    <a href="/user/{{ blog.author.id }}" class="blog-author">{{ blog.author.username }}</a>
                    <div class="text-muted" style="font-size: 0.8rem;">
                        {{ blog.created_at.strftime('%b %d, %Y at %I:%M %p') }}
                        {% if blog.image_url %} • Image Post{% endif %}
                    </div>
                </div>
                <a href="/blog/{{ blog.id }}" class="btn btn-primary btn-sm" style="padding: 8px 16px;">
                    Comments
                </a>
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div class="mobile-card text-center py-5">
        <div style="font-size: 4rem; margin-bottom: 1rem;"></div>
        <h4 class="fw-bold">No Posts Yet</h4>
        <p class="text-muted">Be the first to share your thoughts!</p>
        <a href="/new_blog" class="btn-mobile btn-success-mobile">
            Create First Post
        </a>
    </div>
    {% endif %}
</div>
"""

BLOG_DETAIL_TEMPLATE = """
<div class="blog-card">
    <div class="blog-title">{{ blog.title }}</div>
    {% if blog.image_url %}
    <img src="{{ blog.image_url }}" alt="Post image" class="image-in-post" onclick="openImageModal('{{ blog.image_url }}')">
    {% endif %}
    <div class="blog-content">{{ blog.content }}</div>
    <div class="blog-meta">
        <div>
            <a href="/user/{{ blog.author.id }}" class="blog-author">👤 {{ blog.author.username }}</a>
            <div class="text-muted" style="font-size: 0.8rem;">
                📅 {{ blog.created_at.strftime('%b %d, %Y at %I:%M %p') }}
                {% if blog.image_url %} • 🖼️ Image Post{% endif %}
            </div>
        </div>
        {% if blog.author.id == current_user.id or current_user.is_admin %}
        <form method="POST" action="/delete_blog/{{ blog.id }}" style="display: inline;">
            <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Are you sure you want to delete this post?')">
                <i class="fas fa-trash me-1"></i>Delete
            </button>
        </form>
        {% endif %}
    </div>
</div>

<div class="comment-section">
    <h5 class="fw-bold mb-3">💬 Comments ({{ blog.comments|length }})</h5>
    
    {% if blog.comments %}
        {% for comment in blog.comments %}
        <div class="comment-card">
            <div class="comment-author">{{ comment.author.username }}</div>
            <div class="comment-content">{{ comment.content }}</div>
            <div class="comment-time">{{ comment.created_at.strftime('%b %d, %Y at %I:%M %p') }}</div>
            {% if current_user.is_admin or comment.author.id == current_user.id %}
            <form method="POST" action="/delete_comment/{{ comment.id }}" style="display: inline;">
                <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Delete this comment?')">
                    <i class="fas fa-trash"></i>
                </button>
                </form>
            {% endif %}
        </div>
        {% endfor %}
    {% else %}
        <p class="text-muted text-center py-3">No comments yet. Be the first to comment!</p>
    {% endif %}
    
    <form method="POST" action="/add_comment/{{ blog.id }}" class="mt-3">
        <div class="input-group">
            <input type="text" name="comment" class="form-control" placeholder="Write a comment..." required>
            <button type="submit" class="btn btn-primary">
                <i class="fas fa-paper-plane"></i>
            </button>
        </div>
    </form>
</div>

<div class="mt-3">
    <a href="/" class="btn btn-outline-secondary">
        <i class="fas fa-arrow-left me-2"></i>Back to All Posts
    </a>
</div>
"""

PROFILE_TEMPLATE = """
<div class="profile-header">
    <div class="profile-avatar">
        {{ current_user.username[0].upper() }}
    </div>
    <h3 class="fw-bold">{{ current_user.username }}</h3>
    <p class="mb-0">Member since {{ current_user.created_at.strftime('%B %Y') }}</p>
    {% if current_user.is_admin %}
    <span class="admin-badge mt-2">👑 ADMIN</span>
    {% endif %}
</div>

<div class="d-flex justify-content-around mb-4">
    <div class="text-center">
        <div class="fw-bold" style="font-size: 1.5rem;">{{ current_user.blogs|length }}</div>
        <div class="text-muted">Posts</div>
    </div>
    <div class="text-center">
        <div class="fw-bold" style="font-size: 1.5rem;">{{ current_user.comments|length }}</div>
        <div class="text-muted">Comments</div>
    </div>
    <div class="text-center">
        <div class="fw-bold" style="font-size: 1.5rem;">{{ current_user.uploaded_images|length }}</div>
        <div class="text-muted">Images</div>
    </div>
</div>

<div class="mb-4">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h4 class="fw-bold mb-0">📝 My Posts</h4>
        <a href="/new_blog" class="btn btn-success btn-sm">
            <i class="fas fa-plus me-1"></i>New Post
        </a>
    </div>
    
    {% if current_user.blogs %}
        {% for blog in current_user.blogs|sort(attribute='created_at', reverse=true) %}
        <div class="blog-card" data-blog-id="{{ blog.id }}">
            <div class="blog-title">{{ blog.title }}</div>
            {% if blog.image_url %}
            <img src="{{ blog.image_url }}" alt="Post image" class="image-in-post" onclick="openImageModal('{{ blog.image_url }}')">
            {% endif %}
            <div class="blog-content">{{ blog.content[:100] }}{% if blog.content|length > 100 %}...{% endif %}</div>
            <div class="blog-meta">
                <div class="text-muted" style="font-size: 0.8rem;">
                    📅 {{ blog.created_at.strftime('%b %d, %Y') }}
                    • 💬 {{ blog.comments|length }} comments
                    {% if blog.image_url %} • 🖼️{% endif %}
                </div>
                <div>
                    <a href="/blog/{{ blog.id }}" class="btn btn-primary btn-sm me-1">
                        <i class="fas fa-eye"></i>
                    </a>
                    <form method="POST" action="/delete_blog/{{ blog.id }}" style="display: inline;">
                        <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Are you sure you want to delete this post?')">
                            <i class="fas fa-trash"></i>
                        </button>
                    </form>
                </div>
            </div>
        </div>
        {% endfor %}
    {% else %}
        <div class="mobile-card text-center py-4">
            <div style="font-size: 3rem; margin-bottom: 1rem;">📝</div>
            <h5 class="fw-bold">No Posts Yet</h5>
            <p class="text-muted">You haven't created any posts yet.</p>
            <a href="/new_blog" class="btn btn-success">Create Your First Post</a>
        </div>
    {% endif %}
</div>

<div class="mobile-card">
    <h5 class="fw-bold mb-3">🖼️ Image Storage</h5>
    <div class="mb-3">
        <div class="d-flex justify-content-between">
            <span>Total Storage:</span>
            <span>{{ current_user.uploaded_images|length }}/{{ current_user.image_limit }} images</span>
        </div>
        {% if current_user.uploaded_images|length >= current_user.image_limit %}
        <div class="alert alert-warning mt-2 p-2">
            <small>⚠️ Storage full! Oldest images will be deleted when you upload new ones.</small>
        </div>
        {% endif %}
    </div>
</div>

<div class="mobile-card">
    <h5 class="fw-bold mb-3">⚙️ Account Settings</h5>
    <a href="/logout" class="btn-mobile btn-danger-mobile">
        <i class="fas fa-sign-out-alt me-2"></i>Logout
    </a>
</div>

<script>
// Add click handlers to blog cards for modal
document.addEventListener('DOMContentLoaded', function() {
    const blogCards = document.querySelectorAll('.blog-card');
    blogCards.forEach(card => {
        card.addEventListener('click', function(e) {
            // Don't trigger if clicking on links or buttons
            if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON' || e.target.closest('a') || e.target.closest('button')) {
                return;
            }
            
            const blogId = this.getAttribute('data-blog-id');
            const title = this.querySelector('.blog-title').textContent;
            const content = this.querySelector('.blog-content').textContent;
            const author = this.querySelector('.blog-author')?.textContent || '{{ current_user.username }}';
            const date = this.querySelector('.text-muted').textContent;
            
            openBlogModal(blogId, title, content, author, date);
        });
    });
});
</script>
"""

USER_PROFILE_TEMPLATE = """
<div class="profile-header">
    <div class="profile-avatar">
        {{ user.username[0].upper() }}
    </div>
    <h3 class="fw-bold">{{ user.username }}</h3>
    <p class="mb-0">Member since {{ user.created_at.strftime('%B %Y') }}</p>
    {% if user.is_admin %}
    <span class="admin-badge mt-2">👑 ADMIN</span>
    {% endif %}
    {% if user.is_banned %}
    <span class="banned-badge mt-2">🚫 BANNED</span>
    {% endif %}
</div>

<div class="d-flex justify-content-around mb-4">
    <div class="text-center">
        <div class="fw-bold" style="font-size: 1.5rem;">{{ user.blogs|length }}</div>
        <div class="text-muted">Posts</div>
    </div>
    <div class="text-center">
        <div class="fw-bold" style="font-size: 1.5rem;">{{ user.comments|length }}</div>
        <div class="text-muted">Comments</div>
    </div>
    <div class="text-center">
        <div class="fw-bold" style="font-size: 1.5rem;">{{ user.uploaded_images|length }}</div>
        <div class="text-muted">Images</div>
    </div>
</div>

<div class="mb-4">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h4 class="fw-bold mb-0">📝 {{ user.username }}'s Posts</h4>
        <div>
            {% if current_user.is_admin and not user.is_admin %}
                {% if user.is_banned %}
                <a href="/admin/unban_user/{{ user.id }}" class="btn btn-success btn-sm me-1">
                    <i class="fas fa-check"></i> Unban
                </a>
                {% else %}
                <a href="/admin/ban_user/{{ user.id }}" class="btn btn-warning btn-sm me-1">
                    <i class="fas fa-ban"></i> Ban
                </a>
                {% endif %}
            {% endif %}
            <a href="/chat/{{ user.id }}" class="btn btn-primary btn-sm">
                <i class="fas fa-comment me-1"></i>Private Chat
            </a>
        </div>
    </div>
    
    {% if user.blogs %}
        {% for blog in user.blogs|sort(attribute='created_at', reverse=true) %}
        <div class="blog-card" data-blog-id="{{ blog.id }}">
            <div class="blog-title">{{ blog.title }}</div>
            {% if blog.image_url %}
            <img src="{{ blog.image_url }}" alt="Post image" class="image-in-post" onclick="openImageModal('{{ blog.image_url }}')">
            {% endif %}
            <div class="blog-content">{{ blog.content[:100] }}{% if blog.content|length > 100 %}...{% endif %}</div>
            <div class="blog-meta">
                <div class="text-muted" style="font-size: 0.8rem;">
                    📅 {{ blog.created_at.strftime('%b %d, %Y') }}
                    • 💬 {{ blog.comments|length }} comments
                    {% if blog.image_url %} • 🖼️{% endif %}
                </div>
                <a href="/blog/{{ blog.id }}" class="btn btn-primary btn-sm">
                    <i class="fas fa-eye"></i>
                </a>
            </div>
        </div>
        {% endfor %}
    {% else %}
        <div class="mobile-card text-center py-4">
            <div style="font-size: 3rem; margin-bottom: 1rem;">📝</div>
            <h5 class="fw-bold">No Posts Yet</h5>
            <p class="text-muted">{{ user.username }} hasn't created any posts yet.</p>
        </div>
    {% endif %}
</div>

<div class="mt-3">
    <a href="/users" class="btn btn-outline-secondary">
        <i class="fas fa-arrow-left me-2"></i>Back to All Users
    </a>
</div>

<script>
// Add click handlers to blog cards for modal
document.addEventListener('DOMContentLoaded', function() {
    const blogCards = document.querySelectorAll('.blog-card');
    blogCards.forEach(card => {
        card.addEventListener('click', function(e) {
            // Don't trigger if clicking on links or buttons
            if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON' || e.target.closest('a') || e.target.closest('button')) {
                return;
            }
            
            const blogId = this.getAttribute('data-blog-id');
            const title = this.querySelector('.blog-title').textContent;
            const content = this.querySelector('.blog-content').textContent;
            const author = '{{ user.username }}';
            const date = this.querySelector('.text-muted').textContent;
            
            openBlogModal(blogId, title, content, author, date);
        });
    });
});
</script>
"""

USERS_TEMPLATE = """
<div class="mb-4">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2 class="fw-bold mb-0">👥 Community Members</h2>
        <span class="badge bg-primary">{{ users|length }} users</span>
    </div>
    
    <div class="search-container">
        <input type="text" id="searchInput" class="search-input" placeholder="🔍 Search by username..." onkeyup="searchUsers()">
    </div>
    
    <p class="text-muted">Connect with other members and start conversations</p>
    
    {% if users %}
    <div class="user-list" id="userList">
        {% for user in users %}
        {% if user.id != current_user.id %}
        <a href="/user/{{ user.id }}" class="text-decoration-none user-item">
            <div class="user-card">
                <div class="user-avatar">
                    {{ user.username[0].upper() }}
                </div>
                <div class="user-info">
                    <div class="user-name">{{ user.username }}</div>
                    <div class="user-stats">
                        {{ user.blogs|length }} posts • {{ user.comments|length }} comments
                        {% if user.is_admin %}
                        <span class="admin-badge ms-2">ADMIN</span>
                        {% endif %}
                        {% if user.is_banned %}
                        <span class="banned-badge ms-2">BANNED</span>
                        {% endif %}
                    </div>
                </div>
                <div class="text-primary">
                    <i class="fas fa-chevron-right"></i>
                </div>
            </div>
        </a>
        {% endif %}
        {% endfor %}
    </div>
    {% else %}
    <div class="mobile-card text-center py-5">
        <div style="font-size: 4rem; margin-bottom: 1rem;">👥</div>
        <h4 class="fw-bold">No Other Users</h4>
        <p class="text-muted">You're the first member! Share the app with others.</p>
    </div>
    {% endif %}
</div>

<script>
function searchUsers() {
    const input = document.getElementById('searchInput');
    const filter = input.value.toLowerCase();
    const userList = document.getElementById('userList');
    const users = userList.getElementsByClassName('user-item');
    
    for (let i = 0; i < users.length; i++) {
        const username = users[i].querySelector('.user-name').textContent.toLowerCase();
        if (username.includes(filter)) {
            users[i].style.display = '';
        } else {
            users[i].style.display = 'none';
        }
    }
}

// Focus search input on page load
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.focus();
    }
});
</script>
"""

PRIVATE_CHATS_TEMPLATE = """
<div class="mb-4">
    <h2 class="fw-bold mb-3">💬 Private Chats</h2>
    
    <div class="alert alert-info mb-4">
        <i class="fas fa-info-circle me-2"></i>
        <strong>Note:</strong> Refresh the page to see new messages. Real-time chat is disabled for better performance.
    </div>
    
    <div class="mb-4">
        <h4 class="fw-bold mb-3">📱 Existing Conversations</h4>
        {% if existing_chats %}
        <div class="user-list">
            {% for user_data in existing_chats %}
            <a href="/chat/{{ user_data.user.id }}" class="text-decoration-none">
                <div class="user-card">
                    <div class="user-avatar">
                        {{ user_data.user.username[0].upper() }}
                    </div>
                    <div class="user-info">
                        <div class="user-name">{{ user_data.user.username }}</div>
                        <div class="chat-preview">Last activity: {{ user_data.latest_time.strftime('%b %d, %I:%M %p') }}</div>
                    </div>
                    <div class="text-primary">
                        <i class="fas fa-chevron-right"></i>
                    </div>
                </div>
            </a>
            {% endfor %}
        </div>
        {% else %}
        <div class="mobile-card text-center py-4">
            <div style="font-size: 3rem; margin-bottom: 1rem;">💬</div>
            <h5 class="fw-bold">No Conversations Yet</h5>
            <p class="text-muted">Start a new chat with someone below!</p>
        </div>
        {% endif %}
    </div>
    
    <div>
        <h4 class="fw-bold mb-3">👥 Start New Chat</h4>
        {% if all_users %}
        <div class="user-list">
            {% for user in all_users %}
            <a href="/chat/{{ user.id }}" class="text-decoration-none">
                <div class="user-card">
                    <div class="user-avatar">
                        {{ user.username[0].upper() }}
                    </div>
                    <div class="user-info">
                        <div class="user-name">{{ user.username }}</div>
                        <div class="user-stats">{{ user.blogs|length }} posts • {{ user.comments|length }} comments</div>
                    </div>
                    <div class="text-primary">
                        <i class="fas fa-chevron-right"></i>
                    </div>
                </div>
            </a>
            {% endfor %}
        </div>
        {% else %}
        <div class="mobile-card text-center py-4">
            <div style="font-size: 3rem; margin-bottom: 1rem;">👥</div>
            <h5 class="fw-bold">No Other Users</h5>
            <p class="text-muted">You're the only user right now.</p>
        </div>
        {% endif %}
    </div>
</div>
"""

PRIVATE_CHAT_TEMPLATE = """
<div class="mb-3">
    <div class="alert alert-info">
        <i class="fas fa-info-circle me-2"></i>
        <strong>Note:</strong> Refresh the page to see new messages. Real-time chat is disabled for better performance.
    </div>
</div>

<div class="chat-container">
    <div class="chat-header">
        <i class="fas fa-user me-2"></i>Chat with {{ receiver.username }}
    </div>
    
    <div class="chat-messages" id="chatMessages">
        <div class="text-center text-muted py-4">
            <i class="fas fa-comments fa-2x mb-2"></i>
            <p>Start a private conversation with {{ receiver.username }}...</p>
        </div>
    </div>
    
    <form method="POST" action="/send_private_message/{{ receiver.id }}" class="chat-input-container" enctype="multipart/form-data">
        <input type="text" name="message" class="chat-input" placeholder="Type a message..." autocomplete="off">
        
        <!-- NEW: Image upload for chat -->
        <label for="chatImage{{ receiver.id }}" class="btn btn-success btn-sm mb-0" style="padding: 10px; border-radius: 50%;">
            <i class="fas fa-image"></i>
        </label>
        <input type="file" name="image" id="chatImage{{ receiver.id }}" style="display: none;" accept="image/*">
        
        <button type="submit" class="send-btn">
            <i class="fas fa-paper-plane"></i>
        </button>
    </form>
</div>

<script>
function loadChatHistory() {
    fetch('/private_chat_history/' + {{ receiver.id }})
        .then(response => response.json())
        .then(messages => {
            const chatMessages = document.getElementById('chatMessages');
            chatMessages.innerHTML = '';
            
            if (messages.length === 0) {
                chatMessages.innerHTML = `
                    <div class="text-center text-muted py-4">
                        <i class="fas fa-comments fa-2x mb-2"></i>
                        <p>Start a private conversation with {{ receiver.username }}...</p>
                    </div>
                `;
            } else {
                messages.forEach(msg => {
                    addMessageToChat(msg.sender_id, msg.message_text, msg.sender_name, msg.timestamp, msg.image_url, msg.is_image_message);
                });
            }
            scrollToBottom();
        })
        .catch(error => {
            console.error('Error loading chat history:', error);
        });
}

function addMessageToChat(sender, message, sender_name, timestamp, image_url, is_image_message) {
    const chatMessages = document.getElementById('chatMessages');
    
    if (chatMessages.querySelector('.text-muted')) {
        chatMessages.innerHTML = '';
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender === {{ current_user.id }} ? 'my-message' : 'their-message'}`;
    
    const time = new Date(timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    
    let messageContent = '';
    if (is_image_message && image_url) {
        messageContent = `<img src="${image_url}" alt="Chat image" class="image-message" onclick="openImageModal('${image_url}')">`;
        if (message) {
            messageContent += `<div>${message}</div>`;
        }
    } else {
        messageContent = `<div>${message}</div>`;
    }
    
    messageDiv.innerHTML = `
        ${messageContent}
        <div class="message-time">${sender_name} • ${time}</div>
    `;
    
    chatMessages.appendChild(messageDiv);
}

function scrollToBottom() {
    const chatMessages = document.getElementById('chatMessages');
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

document.addEventListener('DOMContentLoaded', function() {
    loadChatHistory();
    
    // Focus input field
    const chatInput = document.querySelector('.chat-input');
    if (chatInput) {
        chatInput.focus();
    }
});

function adjustChatHeight() {
    const chatContainer = document.querySelector('.chat-container');
    if (chatContainer) {
        const windowHeight = window.innerHeight;
        const headerHeight = document.querySelector('.sticky-header').offsetHeight;
        const inputHeight = document.querySelector('.chat-input-container').offsetHeight;
        chatContainer.style.height = (windowHeight - headerHeight - inputHeight - 40) + 'px';
    }
}

window.addEventListener('resize', adjustChatHeight);
window.addEventListener('load', adjustChatHeight);
setTimeout(adjustChatHeight, 100);
</script>

<div class="mt-3">
    <a href="/private_chats" class="btn btn-outline-secondary">
        <i class="fas fa-arrow-left me-2"></i>Back to Messages
    </a>
</div>
"""

GROUP_CHAT_TEMPLATE = """
<div class="mb-3">
    <div class="alert alert-info">
        <i class="fas fa-info-circle me-2"></i>
        <strong>Note:</strong> Refresh the page to see new messages. Real-time chat is disabled for better performance.
    </div>
</div>

<div class="chat-container">
    <div class="chat-header">
        <i class="fas fa-users me-2"></i>Global Group Chat
    </div>
    
    <div class="chat-messages" id="chatMessages">
        <div class="text-center text-muted py-4">
            <i class="fas fa-users fa-2x mb-2"></i>
            <p>Welcome to the global chat! Say hello to everyone 👋</p>
        </div>
    </div>
    
    <form method="POST" action="/send_group_message" class="chat-input-container" enctype="multipart/form-data">
        <input type="text" name="message" class="chat-input" placeholder="Type a message for everyone..." autocomplete="off">
        
        <!-- NEW: Image upload for group chat -->
        <label for="groupChatImage" class="btn btn-success btn-sm mb-0" style="padding: 10px; border-radius: 50%;">
            <i class="fas fa-image"></i>
        </label>
        <input type="file" name="image" id="groupChatImage" style="display: none;" accept="image/*">
        
        <button type="submit" class="send-btn">
            <i class="fas fa-paper-plane"></i>
        </button>
    </form>
</div>

<script>
function loadGroupChatHistory() {
    fetch('/group_chat_history')
        .then(response => response.json())
        .then(messages => {
            const chatMessages = document.getElementById('chatMessages');
            chatMessages.innerHTML = '';
            
            if (messages.length === 0) {
                chatMessages.innerHTML = `
                    <div class="text-center text-muted py-4">
                        <i class="fas fa-users fa-2x mb-2"></i>
                        <p>Welcome to the global chat! Say hello to everyone 👋</p>
                    </div>
                `;
            } else {
                messages.forEach(msg => {
                    addMessageToChat(msg.sender_id, msg.message_text, msg.sender_name, msg.timestamp, msg.image_url, msg.is_image_message);
                });
            }
            scrollToBottom();
        })
        .catch(error => {
            console.error('Error loading group chat history:', error);
        });
}

function addMessageToChat(sender, message, sender_name, timestamp, image_url, is_image_message) {
    const chatMessages = document.getElementById('chatMessages');
    
    if (chatMessages.querySelector('.text-muted')) {
        chatMessages.innerHTML = '';
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = 'group-message';
    
    const time = new Date(timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    
    let messageContent = '';
    if (is_image_message && image_url) {
        messageContent = `<img src="${image_url}" alt="Chat image" class="image-message" onclick="openImageModal('${image_url}')">`;
        if (message) {
            messageContent += `<div>${message}</div>`;
        }
    } else {
        messageContent = `<div>${message}</div>`;
    }
    
    messageDiv.innerHTML = `
        <div class="message-sender">${sender_name} ${sender === {{ current_user.id }} ? '(You)' : ''}</div>
        ${messageContent}
        <div class="message-time">${time}</div>
    `;
    
    chatMessages.appendChild(messageDiv);
}

function scrollToBottom() {
    const chatMessages = document.getElementById('chatMessages');
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

document.addEventListener('DOMContentLoaded', function() {
    loadGroupChatHistory();
    
    // Focus input field
    const chatInput = document.querySelector('.chat-input');
    if (chatInput) {
        chatInput.focus();
    }
});

function adjustChatHeight() {
    const chatContainer = document.querySelector('.chat-container');
    if (chatContainer) {
        const windowHeight = window.innerHeight;
        const headerHeight = document.querySelector('.sticky-header').offsetHeight;
        const inputHeight = document.querySelector('.chat-input-container').offsetHeight;
        chatContainer.style.height = (windowHeight - headerHeight - inputHeight - 40) + 'px';
    }
}

window.addEventListener('resize', adjustChatHeight);
window.addEventListener('load', adjustChatHeight);
setTimeout(adjustChatHeight, 100);
</script>

<div class="mt-3">
    <a href="/" class="btn btn-outline-secondary">
        <i class="fas fa-arrow-left me-2"></i>Back to Home
    </a>
</div>
"""

ADMIN_DASHBOARD_TEMPLATE = """
<div class="mb-4">
    <h2 class="fw-bold mb-4">👑 Admin Dashboard</h2>
    
    <div class="row g-3 mb-4">
        <div class="col-6">
            <div class="mobile-card text-center bg-primary text-white">
                <h3>{{ stats.total_users }}</h3>
                <p>Total Users</p>
            </div>
        </div>
        <div class="col-6">
            <div class="mobile-card text-center bg-success text-white">
                <h3>{{ stats.total_blogs }}</h3>
                <p>Total Posts</p>
            </div>
        </div>
        <div class="col-6">
            <div class="mobile-card text-center bg-info text-white">
                <h3>{{ stats.total_comments }}</h3>
                <p>Total Comments</p>
            </div>
        </div>
        <div class="col-6">
            <div class="mobile-card text-center bg-warning text-white">
                <h3>{{ stats.banned_users }}</h3>
                <p>Banned Users</p>
            </div>
        </div>
    </div>
    
    <div class="mobile-card mb-4">
        <h4 class="fw-bold mb-3">⚡ Quick Actions</h4>
        <div class="d-grid gap-2">
            <a href="/admin/users" class="btn-mobile btn-primary-mobile">
                👥 Manage Users
            </a>
            <a href="/admin/blogs" class="btn-mobile btn-success-mobile">
                📝 Moderate Posts
            </a>
            <a href="/admin/comments" class="btn-mobile btn-info-mobile">
                💬 Moderate Comments
            </a>
            <a href="/admin/credentials" class="btn-mobile btn-warning-mobile">
                🔐 View Credentials
            </a>
            <a href="/admin/slider" class="btn-mobile btn-secondary-mobile">
                🖼️ Manage Slider
            </a>
            <a href="/admin/chats" class="btn-mobile btn-dark-mobile">
                🔍 Monitor Chats
            </a>
        </div>
    </div>
    
    <div class="row">
        <div class="col-md-6">
            <div class="mobile-card">
                <h5 class="fw-bold">🆕 Recent Users</h5>
                {% for user in recent_users %}
                <div class="user-card">
                    <div class="user-avatar">{{ user.username[0].upper() }}</div>
                    <div class="user-info">
                        <div class="user-name">{{ user.username }}</div>
                        <div class="user-stats">{{ user.blogs|length }} posts</div>
                    </div>
                    {% if user.is_banned %}
                    <span class="banned-badge">BANNED</span>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
        </div>
        <div class="col-md-6">
            <div class="mobile-card">
                <h5 class="fw-bold">📝 Recent Posts</h5>
                {% for blog in recent_blogs %}
                <div class="blog-card" data-blog-id="{{ blog.id }}">
                    <div class="blog-title">{{ blog.title[:30] }}{% if blog.title|length > 30 %}...{% endif %}</div>
                    <div class="blog-meta">
                        <small>By {{ blog.author.username }}</small>
                        <a href="/blog/{{ blog.id }}" class="btn btn-primary btn-sm">
                            <i class="fas fa-eye"></i>
                        </a>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
</div>

<script>
// Add click handlers to blog cards for modal
document.addEventListener('DOMContentLoaded', function() {
    const blogCards = document.querySelectorAll('.blog-card');
    blogCards.forEach(card => {
        card.addEventListener('click', function(e) {
            // Don't trigger if clicking on links or buttons
            if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON' || e.target.closest('a') || e.target.closest('button')) {
                return;
            }
            
            const blogId = this.getAttribute('data-blog-id');
            const title = this.querySelector('.blog-title').textContent;
            const content = 'Click "View Full Post" to read the complete content and comments.';
            const author = this.querySelector('small').textContent.replace('By ', '');
            const date = 'Recent';
            
            openBlogModal(blogId, title, content, author, date);
        });
    });
});
</script>
"""

ADMIN_USERS_TEMPLATE = """
<div class="mb-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="fw-bold mb-0">👥 User Management</h2>
        <a href="/admin" class="btn btn-outline-primary">
            <i class="fas fa-arrow-left me-2"></i>Back to Dashboard
        </a>
    </div>
    
    {% if users %}
    <div class="user-list">
        {% for user in users %}
        <div class="user-card">
            <div class="user-avatar">
                {{ user.username[0].upper() }}
            </div>
            <div class="user-info">
                <div class="user-name">
                    {{ user.username }}
                    {% if user.is_admin %}
                    <span class="admin-badge ms-2">ADMIN</span>
                    {% endif %}
                    {% if user.is_banned %}
                    <span class="banned-badge ms-2">BANNED</span>
                    {% endif %}
                </div>
                <div class="user-stats">
                    {{ user.blogs|length }} posts • {{ user.comments|length }} comments
                    • {{ user.uploaded_images|length }} images
                    • Joined {{ user.created_at.strftime('%b %d, %Y') }}
                </div>
            </div>
            <div class="d-flex gap-2">
                {% if not user.is_admin %}
                    {% if user.is_banned %}
                    <a href="/admin/unban_user/{{ user.id }}" class="btn btn-success btn-sm">
                        <i class="fas fa-check"></i> Unban
                    </a>
                    {% else %}
                    <a href="/admin/ban_user/{{ user.id }}" class="btn btn-warning btn-sm">
                        <i class="fas fa-ban"></i> Ban
                    </a>
                    {% endif %}
                {% endif %}
                <a href="/user/{{ user.id }}" class="btn btn-primary btn-sm">
                    <i class="fas fa-eye"></i>
                </a>
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div class="mobile-card text-center py-5">
        <div style="font-size: 4rem; margin-bottom: 1rem;">👥</div>
        <h4 class="fw-bold">No Users</h4>
        <p class="text-muted">No users found in the system.</p>
    </div>
    {% endif %}
</div>
"""

ADMIN_BLOGS_TEMPLATE = """
<div class="mb-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="fw-bold mb-0">📝 Post Moderation</h2>
        <a href="/admin" class="btn btn-outline-primary">
            <i class="fas fa-arrow-left me-2"></i>Back to Dashboard
        </a>
    </div>
    
    {% if blogs %}
    <div class="blog-list">
        {% for blog in blogs %}
        <div class="blog-card" data-blog-id="{{ blog.id }}">
            <div class="blog-title">{{ blog.title }}</div>
            {% if blog.image_url %}
            <img src="{{ blog.image_url }}" alt="Post image" class="image-in-post" onclick="openImageModal('{{ blog.image_url }}')">
            {% endif %}
            <div class="blog-content">{{ blog.content[:150] }}{% if blog.content|length > 150 %}...{% endif %}</div>
            <div class="blog-meta">
                <div>
                    <a href="/user/{{ blog.author.id }}" class="blog-author">👤 {{ blog.author.username }}</a>
                    <div class="text-muted" style="font-size: 0.8rem;">
                        📅 {{ blog.created_at.strftime('%b %d, %Y at %I:%M %p') }}
                        • 💬 {{ blog.comments|length }} comments
                        {% if blog.image_url %} • 🖼️{% endif %}
                    </div>
                </div>
                <div>
                    <a href="/blog/{{ blog.id }}" class="btn btn-primary btn-sm me-1">
                        <i class="fas fa-eye"></i>
                    </a>
                    <form method="POST" action="/admin/delete_blog/{{ blog.id }}" style="display: inline;">
                        <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Delete this post?')">
                            <i class="fas fa-trash"></i>
                        </button>
                    </form>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div class="mobile-card text-center py-5">
        <div style="font-size: 4rem; margin-bottom: 1rem;">📝</div>
        <h4 class="fw-bold">No Posts</h4>
        <p class="text-muted">No posts found in the system.</p>
    </div>
    {% endif %}
</div>

<script>
// Add click handlers to blog cards for modal
document.addEventListener('DOMContentLoaded', function() {
    const blogCards = document.querySelectorAll('.blog-card');
    blogCards.forEach(card => {
        card.addEventListener('click', function(e) {
            // Don't trigger if clicking on links or buttons
            if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON' || e.target.closest('a') || e.target.closest('button')) {
                return;
            }
            
            const blogId = this.getAttribute('data-blog-id');
            const title = this.querySelector('.blog-title').textContent;
            const content = this.querySelector('.blog-content').textContent;
            const author = this.querySelector('.blog-author').textContent;
            const date = this.querySelector('.text-muted').textContent;
            
            openBlogModal(blogId, title, content, author, date);
        });
    });
});
</script>
"""

ADMIN_COMMENTS_TEMPLATE = """
<div class="mb-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="fw-bold mb-0">💬 Comment Moderation</h2>
        <a href="/admin" class="btn btn-outline-primary">
            <i class="fas fa-arrow-left me-2"></i>Back to Dashboard
        </a>
    </div>
    
    {% if comments %}
    <div class="comment-list">
        {% for comment in comments %}
        <div class="comment-card">
            <div class="comment-author">{{ comment.author.username }}</div>
            <div class="comment-content">{{ comment.content }}</div>
            <div class="comment-time">
                On post: "{{ comment.blog.title[:30] }}..." • 
                {{ comment.created_at.strftime('%b %d, %Y at %I:%M %p') }}
            </div>
            <div class="mt-2">
                <a href="/blog/{{ comment.blog.id }}" class="btn btn-primary btn-sm me-1">
                    <i class="fas fa-eye"></i> View Post
                </a>
                <form method="POST" action="/admin/delete_comment/{{ comment.id }}" style="display: inline;">
                    <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Delete this comment?')">
                        <i class="fas fa-trash"></i> Delete
                    </button>
                </form>
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div class="mobile-card text-center py-5">
        <div style="font-size: 4rem; margin-bottom: 1rem;">💬</div>
        <h4 class="fw-bold">No Comments</h4>
        <p class="text-muted">No comments found in the system.</p>
    </div>
    {% endif %}
</div>
"""

ADMIN_CREDENTIALS_TEMPLATE = """
<div class="mb-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="fw-bold mb-0">🔐 User Credentials</h2>
        <a href="/admin" class="btn btn-outline-primary">
            <i class="fas fa-arrow-left me-2"></i>Back to Dashboard
        </a>
    </div>

    <div class="alert alert-warning mb-4">
        <i class="fas fa-exclamation-triangle me-2"></i>
        <strong>Security Notice:</strong> This information is sensitive. Use only for security purposes.
    </div>

    {% if users %}
    <div class="mobile-card">
        <div class="table-responsive">
            <table class="credentials-table">
                <thead>
                    <tr>
                        <th>Username</th>
                        <th>Email</th>
                        <th>Password Hash</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in users %}
                    <tr>
                        <td>
                            <div class="credential-field">
                                <span class="credential-text">{{ user.username }}</span>
                                <button class="copy-credential" onclick="copyCredential('{{ user.username }}', 'Username')">
                                    <i class="fas fa-copy"></i>
                                </button>
                            </div>
                            {% if user.is_admin %}<span class="admin-badge ms-1">ADMIN</span>{% endif %}
                        </td>
                        <td>
                            <div class="credential-field">
                                <span class="credential-text">{{ user.email }}</span>
                                <button class="copy-credential" onclick="copyCredential('{{ user.email }}', 'Email')">
                                    <i class="fas fa-copy"></i>
                                </button>
                            </div>
                        </td>
                        <td>
                            <div class="credential-field">
                                <span class="credential-text" title="{{ user.password_hash }}">
                                    {{ user.password_hash[:20] }}...
                                </span>
                                <button class="copy-credential" onclick="copyCredential('{{ user.password_hash }}', 'Password Hash')">
                                    <i class="fas fa-copy"></i>
                                </button>
                            </div>
                        </td>
                        <td>
                            {% if user.is_banned %}
                            <span class="banned-badge">BANNED</span>
                            {% else %}
                            <span class="badge bg-success">ACTIVE</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    {% else %}
    <div class="mobile-card text-center py-5">
        <div style="font-size: 4rem; margin-bottom: 1rem;">👥</div>
        <h4 class="fw-bold">No Users</h4>
        <p class="text-muted">No users found in the system.</p>
    </div>
    {% endif %}
</div>
"""

ADMIN_SLIDER_TEMPLATE = """
<div class="mb-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="fw-bold mb-0">🖼️ Admin Slider Management</h2>
        <a href="/admin" class="btn btn-outline-primary">
            <i class="fas fa-arrow-left me-2"></i>Back to Dashboard
        </a>
    </div>

    <div class="mobile-card mb-4">
        <h4 class="fw-bold mb-3">➕ Add New Slide</h4>
        <form method="POST" action="/admin/add_slide" enctype="multipart/form-data">
            <input type="text" name="title" class="input-mobile" placeholder="Slide Title (optional)">
            <textarea name="content" class="input-mobile" placeholder="Slide Content (optional)" rows="3"></textarea>
            <input type="file" name="image" class="input-mobile" accept="image/*">
            <button type="submit" class="btn-mobile btn-success-mobile">
                <i class="fas fa-plus me-2"></i>Add Slide
            </button>
        </form>
    </div>

    <div class="mobile-card">
        <h4 class="fw-bold mb-3">📋 Current Slides</h4>
        {% if slides %}
        <div class="row">
            {% for slide in slides %}
            <div class="col-md-6 mb-3">
                <div class="border rounded p-3">
                    {% if slide.image_path %}
                    <img src="{{ url_for('static', filename=slide.image_path) }}" alt="Slide {{ slide.id }}" 
                         style="max-width: 100%; height: 100px; object-fit: cover; border-radius: 8px;" class="mb-2"
                         onclick="openImageModal('{{ url_for('static', filename=slide.image_path) }}')"
                         style="cursor: pointer;">
                    {% endif %}
                    {% if slide.title %}<h6 class="fw-bold">{{ slide.title }}</h6>{% endif %}
                    {% if slide.content %}<p class="small">{{ slide.content }}</p>{% endif %}
                    <div class="d-flex gap-2">
                        <form method="POST" action="/admin/delete_slide/{{ slide.id }}" style="display: inline;">
                            <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Delete this slide?')">
                                <i class="fas fa-trash"></i> Delete
                            </button>
                        </form>
                        {% if not slide.is_active %}
                        <a href="/admin/activate_slide/{{ slide.id }}" class="btn btn-success btn-sm">
                            <i class="fas fa-check"></i> Activate
                        </a>
                        {% else %}
                        <a href="/admin/deactivate_slide/{{ slide.id }}" class="btn btn-warning btn-sm">
                            <i class="fas fa-times"></i> Deactivate
                        </a>
                        {% endif %}
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <p class="text-muted text-center py-4">No slides created yet.</p>
        {% endif %}
    </div>
</div>
"""

ADMIN_CHATS_TEMPLATE = """
<div class="mb-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="fw-bold mb-0">🔍 Chat Monitoring</h2>
        <a href="/admin" class="btn btn-outline-primary">
            <i class="fas fa-arrow-left me-2"></i>Back to Dashboard
        </a>
    </div>

    <div class="alert alert-warning mb-4">
        <i class="fas fa-exclamation-triangle me-2"></i>
        <strong>Privacy Notice:</strong> This monitoring is for safety and moderation purposes only. 
        Respect user privacy and use this power responsibly.
    </div>
    
    <div class="row">
        <div class="col-md-6">
            <div class="mobile-card">
                <h4 class="fw-bold mb-3">🔒 Private Messages</h4>
                <p class="text-muted small mb-3">Latest 100 private conversations</p>
                {% if private_messages %}
                    {% for msg in private_messages %}
                    <div class="message-card mb-3 p-3 border rounded" style="background: #f8f9fa;">
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <strong>👤 {{ msg.sender.username }}</strong>
                                <i class="fas fa-arrow-right mx-2 text-muted"></i>
                                <strong>👤 {{ msg.receiver.username }}</strong>
                            </div>
                            <small class="text-muted">{{ msg.timestamp.strftime("%m/%d %H:%M") }}</small>
                        </div>
                        {% if msg.image_url %}
                        <div class="mt-2">
                            <img src="{{ msg.image_url }}" alt="Message image" class="image-message" onclick="openImageModal('{{ msg.image_url }}')">
                        </div>
                        {% endif %}
                        <div class="mt-2 p-2 bg-white rounded">{{ msg.message_text }}</div>
                        <div class="mt-2 text-end">
                            <small class="text-muted">ID: {{ msg.id }}</small>
                        </div>
                    </div>
                    {% endfor %}
                {% else %}
                    <p class="text-muted text-center py-4">No private messages yet.</p>
                {% endif %}
            </div>
        </div>
        
        <div class="col-md-6">
            <div class="mobile-card">
                <h4 class="fw-bold mb-3">👥 Group Chat Messages</h4>
                <p class="text-muted small mb-3">Latest 100 group messages</p>
                {% if group_messages %}
                    {% for msg in group_messages %}
                    <div class="message-card mb-3 p-3 border rounded" style="background: #f8f9fa;">
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <strong>👤 {{ msg.sender.username }}</strong>
                                <span class="badge bg-info ms-2">GROUP</span>
                            </div>
                            <small class="text-muted">{{ msg.timestamp.strftime("%m/%d %H:%M") }}</small>
                        </div>
                        {% if msg.image_url %}
                        <div class="mt-2">
                            <img src="{{ msg.image_url }}" alt="Message image" class="image-message" onclick="openImageModal('{{ msg.image_url }}')">
                        </div>
                        {% endif %}
                        <div class="mt-2 p-2 bg-white rounded">{{ msg.message_text }}</div>
                        <div class="mt-2 text-end">
                            <small class="text-muted">ID: {{ msg.id }}</small>
                        </div>
                    </div>
                    {% endfor %}
                {% else %}
                    <p class="text-muted text-center py-4">No group messages yet.</p>
                {% endif %}
            </div>
        </div>
    </div>
</div>
"""

@app.route('/')
@login_required
def home():
    blogs = BlogPost.query.order_by(BlogPost.created_at.desc()).all()
    admin_slides = AdminSlider.query.filter_by(is_active=True).order_by(AdminSlider.order_index).all()
    
    content = render_template_string(HOME_TEMPLATE, blogs=blogs)
    return render_template_string(BASE_TEMPLATE, content=content, admin_slides=admin_slides)

@app.route('/register', methods=['GET','POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        # NEW: Check if terms are agreed
        if not request.form.get('agree_terms'):
            flash('❌ You must agree to the Terms & Conditions to register.', 'danger')
            return redirect(url_for('register'))
            
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        
        is_admin = False
        if email == 'god@gmail.com' and password == 'Kunal_8805':
            is_admin = True
            username = 'AlmightyAdmin(KD)'
            flash('🎉 Welcome, Almighty Admin! You have been granted admin privileges.', 'success')
        
        user = User(username=username, email=email, password_hash=hashed_password, is_admin=is_admin)
        try:
            db.session.add(user)
            db.session.commit()
            if not is_admin:
                flash('🎉 Account created successfully! Please login.', 'success')
            return redirect(url_for('login'))
        except:
            db.session.rollback()
            flash('❌ Username or email already exists.', 'danger')
    return render_template_string(BASE_TEMPLATE, content=REGISTER_TEMPLATE)

@app.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        # NEW: Check if terms are agreed
        if not request.form.get('agree_terms'):
            flash('❌ You must agree to the Terms & Conditions to login.', 'danger')
            return redirect(url_for('login'))
            
        login_input = request.form['login']
        password = request.form['password']
        
        # FIXED: Only find user by email (phone removed)
        user = User.query.filter(User.email == login_input).first()
        
        if user and user.password_hash == hashlib.sha256(password.encode()).hexdigest():
            if user.is_banned:
                flash('🚫 Your account has been banned. Contact administrator.', 'danger')
                return redirect(url_for('login'))
            
            # Clear existing session
            session.clear()
            
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            # Set session before login
            session['user_id'] = user.id
            session.permanent = True
            
            login_user(user, remember=False)
            
            if user.is_admin:
                flash(f'👑 Welcome back, Almighty Admin {user.username}!', 'success')
            else:
                flash(f'👋 Welcome back, {user.username}!', 'success')
            
            # Redirect with cache prevention
            response = redirect(url_for('home'))
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
        else:
            flash('❌ Invalid login credentials.', 'danger')
    return render_template_string(BASE_TEMPLATE, content=LOGIN_TEMPLATE)

@app.route('/logout')
@login_required
def logout():
    username = current_user.username
    session.clear()
    logout_user()
    flash(f'👋 {username}, you have been logged out successfully.', 'info')
    
    response = redirect(url_for('login'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/new_blog', methods=['GET','POST'])
@login_required
def new_blog():
    if current_user.is_banned:
        flash('🚫 Your account is banned. You cannot create posts.', 'danger')
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        image_file = request.files.get('image')
        
        # UPDATED: Check image limits - only total limit now
        if image_file and image_file.filename:
            can_upload, limit_type = check_image_limits(current_user)
            if not can_upload:
                # Delete oldest image and proceed
                delete_oldest_images(current_user.id)
                flash('🔄 Storage full! Oldest image deleted to make space.', 'warning')
        
        # Handle image upload
        image_url = None
        if image_file and image_file.filename:
            # Upload to Supabase
            image_url = upload_to_supabase(image_file, image_file.filename, current_user.id)
            if not image_url:
                flash('❌ Failed to upload image. Please try again.', 'danger')
                return redirect(url_for('new_blog'))
            
            # Create UserImage record
            user_image = UserImage(
                user_id=current_user.id,
                image_url=image_url,
                filename=image_file.filename,
                file_size=len(image_file.read()) // 1024,
                used_in_posts=True
            )
            db.session.add(user_image)
            
            # Update user's last upload date
            update_image_usage(current_user)
        
        # Create blog post
        blog = BlogPost(
            user_id=current_user.id, 
            title=title, 
            content=content,
            image_url=image_url,
            is_image_post=bool(image_url)
        )
        db.session.add(blog)
        db.session.commit()
        
        if image_url:
            flash('✅ Image post published successfully!', 'success')
        else:
            flash('✅ Post published successfully!', 'success')
        return redirect(url_for('home'))
    
    content = render_template_string(NEW_BLOG_TEMPLATE)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/blog/<int:blog_id>')
@login_required
def blog_detail(blog_id):
    blog = BlogPost.query.get_or_404(blog_id)
    
    content = render_template_string(BLOG_DETAIL_TEMPLATE, blog=blog)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/add_comment/<int:blog_id>', methods=['POST'])
@login_required
def add_comment(blog_id):
    if current_user.is_banned:
        flash('🚫 Your account is banned. You cannot comment.', 'danger')
        return redirect(f'/blog/{blog_id}')
        
    content = request.form['comment']
    comment = Comment(user_id=current_user.id, blog_id=blog_id, content=content)
    db.session.add(comment)
    db.session.commit()
    flash('💬 Comment added successfully!', 'success')
    return redirect(f'/blog/{blog_id}')

@app.route('/delete_blog/<int:blog_id>', methods=['POST'])
@login_required
def delete_blog(blog_id):
    blog = BlogPost.query.get_or_404(blog_id)
    if blog.author.id != current_user.id and not current_user.is_admin:
        flash('❌ You can only delete your own posts.', 'danger')
        return redirect('/')
    
    db.session.delete(blog)
    db.session.commit()
    flash('🗑️ Post deleted successfully!', 'success')
    return redirect('/')

@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.author.id != current_user.id and not current_user.is_admin:
        flash('❌ You can only delete your own comments.', 'danger')
        return redirect(f'/blog/{comment.blog_id}')
    
    blog_id = comment.blog_id
    db.session.delete(comment)
    db.session.commit()
    flash('🗑️ Comment deleted successfully!', 'success')
    return redirect(f'/blog/{blog_id}')

@app.route('/profile')
@login_required
def profile():
    content = render_template_string(PROFILE_TEMPLATE)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/users')
@login_required
def users():
    all_users = User.query.all()
    
    content = render_template_string(USERS_TEMPLATE, users=all_users)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/user/<int:user_id>')
@login_required
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    
    content = render_template_string(USER_PROFILE_TEMPLATE, user=user)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/chat/<int:receiver_id>')
@login_required
def private_chat(receiver_id):
    if current_user.is_banned:
        flash('🚫 Your account is banned. You cannot send messages.', 'danger')
        return redirect(url_for('home'))
        
    receiver = User.query.get_or_404(receiver_id)
    if receiver.is_banned:
        flash('🚫 This user is banned and cannot receive messages.', 'danger')
        return redirect(url_for('private_chats'))
    
    content = render_template_string(PRIVATE_CHAT_TEMPLATE, receiver=receiver)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/send_private_message/<int:receiver_id>', methods=['POST'])
@login_required
def send_private_message(receiver_id):
    if current_user.is_banned:
        flash('🚫 Your account is banned. You cannot send messages.', 'danger')
        return redirect(url_for('home'))
        
    receiver = User.query.get_or_404(receiver_id)
    if receiver.is_banned:
        flash('🚫 This user is banned and cannot receive messages.', 'danger')
        return redirect(url_for('private_chats'))
    
    message_text = request.form.get('message', '')
    image_file = request.files.get('image')
    
    # Check if it's an image message
    is_image_message = bool(image_file and image_file.filename)
    
    # UPDATED: Handle image upload for chat - only total limit
    image_url = None
    if is_image_message:
        can_upload, limit_type = check_image_limits(current_user)
        if not can_upload:
            # Delete oldest image and proceed
            delete_oldest_images(current_user.id)
            flash('🔄 Storage full! Oldest image deleted to make space.', 'warning')
        
        image_url = upload_to_supabase(image_file, image_file.filename, current_user.id)
        if not image_url:
            flash('❌ Failed to upload image. Please try again.', 'danger')
            return redirect(f'/chat/{receiver_id}')
        
        # Create UserImage record
        user_image = UserImage(
            user_id=current_user.id,
            image_url=image_url,
            filename=image_file.filename,
            file_size=len(image_file.read()) // 1024,
            used_in_chats=True
        )
        db.session.add(user_image)
        
        # Update user's last upload date
        update_image_usage(current_user)
    
    # Create message
    message = Message(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        message_text=message_text,
        image_url=image_url,
        is_image_message=is_image_message
    )
    
    db.session.add(message)
    db.session.commit()
    
    if is_image_message:
        flash('🖼️ Image sent! Refresh to see it in the chat.', 'success')
    else:
        flash('💬 Message sent! Refresh to see it in the chat.', 'success')
    return redirect(f'/chat/{receiver_id}')

@app.route('/private_chats')
@login_required
def private_chats():
    all_users = User.query.filter(User.id != current_user.id, User.is_banned == False).all()
    
    # Get latest chat times for each user
    latest_times = get_latest_chat_time(current_user.id)
    
    # Create list of users with their latest chat time
    existing_chats = []
    for user_id, latest_time in latest_times.items():
        user = User.query.get(user_id)
        if user and not user.is_banned:
            existing_chats.append({
                'user': user,
                'latest_time': latest_time
            })
    
    # Sort by latest time (newest first)
    existing_chats.sort(key=lambda x: x['latest_time'], reverse=True)
    
    content = render_template_string(PRIVATE_CHATS_TEMPLATE, existing_chats=existing_chats, all_users=all_users)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/group_chat')
@login_required
def group_chat():
    if current_user.is_banned:
        flash('🚫 Your account is banned. You cannot send messages.', 'danger')
        return redirect(url_for('home'))
    
    content = render_template_string(GROUP_CHAT_TEMPLATE)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/send_group_message', methods=['POST'])
@login_required
def send_group_message():
    if current_user.is_banned:
        flash('🚫 Your account is banned. You cannot send messages.', 'danger')
        return redirect(url_for('home'))
    
    message_text = request.form.get('message', '')
    image_file = request.files.get('image')
    
    # Check if it's an image message
    is_image_message = bool(image_file and image_file.filename)
    
    # UPDATED: Handle image upload for group chat - only total limit
    image_url = None
    if is_image_message:
        can_upload, limit_type = check_image_limits(current_user)
        if not can_upload:
            # Delete oldest image and proceed
            delete_oldest_images(current_user.id)
            flash('🔄 Storage full! Oldest image deleted to make space.', 'warning')
        
        image_url = upload_to_supabase(image_file, image_file.filename, current_user.id)
        if not image_url:
            flash('❌ Failed to upload image. Please try again.', 'danger')
            return redirect('/group_chat')
        
        # Create UserImage record
        user_image = UserImage(
            user_id=current_user.id,
            image_url=image_url,
            filename=image_file.filename,
            file_size=len(image_file.read()) // 1024,
            used_in_chats=True
        )
        db.session.add(user_image)
        
        # Update user's last upload date
        update_image_usage(current_user)
    
    # Create message
    message = GroupMessage(
        sender_id=current_user.id,
        message_text=message_text,
        image_url=image_url,
        is_image_message=is_image_message
    )
    
    db.session.add(message)
    db.session.commit()
    
    if is_image_message:
        flash('🖼️ Image sent to group! Refresh to see it in the chat.', 'success')
    else:
        flash('💬 Message sent to group! Refresh to see it in the chat.', 'success')
    return redirect('/group_chat')

@app.route('/private_chat_history/<int:receiver_id>')
@login_required
def private_chat_history(receiver_id):
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == receiver_id)) |
        ((Message.sender_id == receiver_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()
    
    messages_data = []
    for msg in messages:
        sender = User.query.get(msg.sender_id)
        messages_data.append({
            'sender_id': msg.sender_id,
            'sender_name': sender.username,
            'message_text': msg.message_text,
            'timestamp': msg.timestamp.isoformat(),
            'image_url': msg.image_url,
            'is_image_message': msg.is_image_message
        })
    
    return jsonify(messages_data)

@app.route('/group_chat_history')
@login_required
def group_chat_history():
    messages = GroupMessage.query.order_by(GroupMessage.timestamp.asc()).limit(100).all()
    
    messages_data = []
    for msg in messages:
        sender = User.query.get(msg.sender_id)
        messages_data.append({
            'sender_id': msg.sender_id,
            'sender_name': sender.username,
            'message_text': msg.message_text,
            'timestamp': msg.timestamp.isoformat(),
            'image_url': msg.image_url,
            'is_image_message': msg.is_image_message
        })
    
    return jsonify(messages_data)

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    total_blogs = BlogPost.query.count()
    total_comments = Comment.query.count()
    
    stats = {
        'total_users': total_users,
        'total_blogs': total_blogs,
        'total_comments': total_comments,
        'banned_users': User.query.filter_by(is_banned=True).count(),
        'today_blogs': BlogPost.query.filter(
            BlogPost.created_at >= datetime.today().date()
        ).count()
    }
    
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    recent_blogs = BlogPost.query.order_by(BlogPost.created_at.desc()).limit(5).all()
    
    content = render_template_string(ADMIN_DASHBOARD_TEMPLATE, stats=stats, recent_users=recent_users, recent_blogs=recent_blogs)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    
    content = render_template_string(ADMIN_USERS_TEMPLATE, users=users)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/admin/blogs')
@login_required
@admin_required
def admin_blogs():
    blogs = BlogPost.query.order_by(BlogPost.created_at.desc()).all()
    
    content = render_template_string(ADMIN_BLOGS_TEMPLATE, blogs=blogs)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/admin/comments')
@login_required
@admin_required
def admin_comments():
    comments = Comment.query.order_by(Comment.created_at.desc()).all()
    
    content = render_template_string(ADMIN_COMMENTS_TEMPLATE, comments=comments)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/admin/credentials')
@login_required
@admin_required
def admin_credentials():
    users = User.query.order_by(User.created_at.desc()).all()
    
    content = render_template_string(ADMIN_CREDENTIALS_TEMPLATE, users=users)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/admin/slider')
@login_required
@admin_required
def admin_slider():
    slides = AdminSlider.query.order_by(AdminSlider.order_index).all()
    
    content = render_template_string(ADMIN_SLIDER_TEMPLATE, slides=slides)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/admin/chats')
@login_required
@admin_required
def admin_chats():
    private_messages = Message.query.order_by(Message.timestamp.desc()).limit(100).all()
    group_messages = GroupMessage.query.order_by(GroupMessage.timestamp.desc()).limit(100).all()
    
    content = render_template_string(ADMIN_CHATS_TEMPLATE, private_messages=private_messages, group_messages=group_messages)
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route('/admin/ban_user/<int:user_id>')
@login_required
@admin_required
def ban_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash('❌ Cannot ban other administrators.', 'danger')
    else:
        user.is_banned = True
        db.session.commit()
        flash(f'🚫 User {user.username} has been banned.', 'success')
    return redirect('/admin/users')

@app.route('/admin/unban_user/<int:user_id>')
@login_required
@admin_required
def unban_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_banned = False
    db.session.commit()
    flash(f'✅ User {user.username} has been unbanned.', 'success')
    return redirect('/admin/users')

@app.route('/admin/delete_blog/<int:blog_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_blog(blog_id):
    blog = BlogPost.query.get_or_404(blog_id)
    db.session.delete(blog)
    db.session.commit()
    flash('🗑️ Post deleted by admin.', 'success')
    return redirect('/admin/blogs')

@app.route('/admin/delete_comment/<int:comment_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    db.session.delete(comment)
    db.session.commit()
    flash('🗑️ Comment deleted by admin.', 'success')
    return redirect('/admin/comments')

@app.route('/admin/add_slide', methods=['POST'])
@login_required
@admin_required
def admin_add_slide():
    title = request.form.get('title')
    content = request.form.get('content')
    image = request.files.get('image')
    
    image_path = None
    if image and image.filename:
        # Secure filename and save
        filename = f"slide_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{image.filename}"
        image_path = f"uploads/{filename}"
        image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    
    # Get the next order index
    max_order = db.session.query(db.func.max(AdminSlider.order_index)).scalar() or 0
    
    slide = AdminSlider(
        title=title,
        content=content,
        image_path=image_path,
        order_index=max_order + 1
    )
    
    db.session.add(slide)
    db.session.commit()
    
    flash('✅ Slide added successfully!', 'success')
    return redirect('/admin/slider')

@app.route('/admin/delete_slide/<int:slide_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_slide(slide_id):
    slide = AdminSlider.query.get_or_404(slide_id)
    
    # Delete image file if exists
    if slide.image_path:
        try:
            os.remove(os.path.join('static', slide.image_path))
        except:
            pass
    
    db.session.delete(slide)
    db.session.commit()
    
    flash('🗑️ Slide deleted successfully!', 'success')
    return redirect('/admin/slider')

def create_admin_user():
    with app.app_context():
        admin_email = 'god@gmail.com'
        admin_password = 'Kunal_8805'
        admin_username = 'AlmightyAdmin(KD)'
        
        existing_admin = User.query.filter_by(email=admin_email).first()
        if not existing_admin:
            hashed_password = hashlib.sha256(admin_password.encode()).hexdigest()
            admin_user = User(
                username=admin_username,
                email=admin_email,
                password_hash=hashed_password,
                is_admin=True
            )
            db.session.add(admin_user)
            db.session.commit()
            print("👑 Admin user created successfully!")
       else:
    # Update existing admin username
    existing_admin.username = admin_username
    existing_admin.is_admin = True
    db.session.commit()
    print("👑 Admin user updated!")


# ---------------------------
# ✅ Robots.txt route
# ---------------------------
@app.route("/robots.txt")
def robots_txt():
    return """User-agent: *
Allow: /
Sitemap: https://tution-area-network-1-zc34.onrender.com/sitemap.xml
""", 200, {"Content-Type": "text/plain"}


# ---------------------------
# ✅ Sitemap.xml route
# ---------------------------
@app.route("/sitemap.xml")
def sitemap_xml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="https://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://tution-area-network-1-zc34.onrender.com/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://tution-area-network-1-zc34.onrender.com/posts</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://tution-area-network-1-zc34.onrender.com/login</loc>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
  </url>
  <url>
    <loc>https://tution-area-network-1-zc34.onrender.com/register</loc>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
  </url>
</urlset>
""", 200, {"Content-Type": "application/xml"}


# ---------------------------
# ✅ Main Flask runner
# ---------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_admin_user()
        cleanup_old_messages()
    
    # Clear all sessions on startup
    with app.test_request_context():
        session.clear()
    
    port = int(os.environ.get('PORT', 5001))          # ← ADD THIS LINE
    app.run(host='0.0.0.0', port=port)                # ← REPLACE THIS LINE
