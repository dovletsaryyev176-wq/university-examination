from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from werkzeug.security import generate_password_hash
from database import get_db_connection

users_bp = Blueprint('users', __name__)

@users_bp.route('/')
@login_required
def index():
    db = get_db_connection()
    users = db.execute('SELECT id, full_name, username FROM users').fetchall()
    db.close()
    return render_template('users/list.html', users=users)

@users_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        username = request.form.get('username', '').strip()
        password_raw = request.form.get('password', '')

        if not full_name or not username or not password_raw:
            flash("Ähli meýdançalary dolduryň")
            return render_template('users/form.html', user=None)

        password = generate_password_hash(password_raw)

        db = get_db_connection()
        try:
            db.execute('INSERT INTO users (full_name, username, password) VALUES (?, ?, ?)',
                       (full_name, username, password))
            db.commit()
            flash(f"Ulanyjy {username} döredilen")
            return redirect(url_for('users.index'))
        except Exception:
            flash("Ýalňyş: bu ulanyjy eýýäm bar")
        finally:
            db.close()
            
    return render_template('users/form.html', user=None)

@users_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    db = get_db_connection()
    user = db.execute('SELECT * FROM users WHERE id = ?', (id,)).fetchone()

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        username = request.form.get('username', '').strip()
        password_raw = request.form.get('password', '')

        if password_raw:
            hashed_pw = generate_password_hash(password_raw)
            db.execute('UPDATE users SET full_name = ?, username = ?, password = ? WHERE id = ?',
                       (full_name, username, hashed_pw, id))
        else:
            db.execute('UPDATE users SET full_name = ?, username = ? WHERE id = ?',
                       (full_name, username, id))
            
        db.commit()
        db.close()
        flash("Maglumatlar üstünikli üýtgedildi")
        return redirect(url_for('users.index'))

    db.close()
    if not user:
        flash("Ulanyjy tapylmady")
        return redirect(url_for('users.index'))
        
    return render_template('users/form.html', user=user)

@users_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    db = get_db_connection()
    db.execute('DELETE FROM users WHERE id = ?', (id,))
    db.commit()
    db.close()
    flash("Ulanyjy ýok edildi")
    return redirect(url_for('users.index'))