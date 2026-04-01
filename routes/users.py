from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from werkzeug.security import generate_password_hash
from database import get_db_connection

# Инициализируем Blueprint для работы в составе app.py
users_bp = Blueprint('users', __name__)

# --- READ: Список всех пользователей ---
@users_bp.route('/')
@login_required
def index():
    db = get_db_connection()
    users = db.execute('SELECT id, full_name, username FROM users').fetchall()
    db.close()
    return render_template('users/list.html', users=users)

# --- CREATE: Создание нового пользователя ---
@users_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        full_name = request.form['full_name']
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        db = get_db_connection()
        try:
            db.execute('INSERT INTO users (full_name, username, password) VALUES (?, ?, ?)',
                       (full_name, username, password))
            db.commit()
            flash(f"Пользователь {username} успешно создан")
            return redirect(url_for('users.index'))
        except:
            flash("Ошибка: такое имя пользователя уже существует")
        finally:
            db.close()
            
    return render_template('users/form.html', user=None)

# --- UPDATE: Редактирование данных ---
@users_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    db = get_db_connection()
    user = db.execute('SELECT * FROM users WHERE id = ?', (id,)).fetchone()

    if request.method == 'POST':
        full_name = request.form['full_name']
        username = request.form['username']
        password_raw = request.form['password']
        
        # Если пароль ввели, хешируем и обновляем. Если пусто — оставляем старый.
        if password_raw:
            hashed_pw = generate_password_hash(password_raw)
            db.execute('UPDATE users SET full_name = ?, username = ?, password = ? WHERE id = ?',
                       (full_name, username, hashed_pw, id))
        else:
            db.execute('UPDATE users SET full_name = ?, username = ? WHERE id = ?',
                       (full_name, username, id))
            
        db.commit()
        db.close()
        flash("Данные успешно обновлены")
        return redirect(url_for('users.index'))

    db.close()
    if not user:
        flash("Пользователь не найден")
        return redirect(url_for('users.index'))
        
    return render_template('users/form.html', user=user)

# --- DELETE: Удаление (только через POST) ---
@users_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    db = get_db_connection()
    db.execute('DELETE FROM users WHERE id = ?', (id,))
    db.commit()
    db.close()
    flash("Пользователь удален")
    return redirect(url_for('users.index'))