from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import UserMixin, login_user, logout_user
from werkzeug.security import check_password_hash
from database import get_db_connection

auth_bp = Blueprint('auth', __name__)

class User(UserMixin):
    def __init__(self, id, username, full_name):
        self.id = id
        self.username = username
        self.full_name = full_name

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        db = get_db_connection()
        user_data = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        db.close()
        
        if user_data and check_password_hash(user_data['password'], password):
            user_obj = User(user_data['id'], user_data['username'], user_data['full_name'])
            login_user(user_obj)
            return redirect(url_for('users.index'))
        
        flash('Неверный логин или пароль')
    return render_template('auth/login.html')

@auth_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))