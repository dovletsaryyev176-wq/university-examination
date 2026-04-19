from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from database import get_db_connection

subjects_bp = Blueprint('subjects', __name__)

@subjects_bp.route('/')
@login_required
def index():
    db = get_db_connection()
    # Получаем все предметы, чтобы видеть и активные, и заблокированные
    subjects = db.execute('SELECT * FROM subjects ORDER BY name ASC').fetchall()
    db.close()
    return render_template('subjects/list.html', subjects=subjects)

@subjects_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        name = request.form['name'].strip()
        answer_count = request.form.get('answer_count', 4, type=int)
        if not name:
            flash("Название не может быть пустым", "danger")
        elif answer_count not in range(2, 6):
            flash("Количество вариантов ответа должно быть от 2 до 5", "danger")
        else:
            db = get_db_connection()
            try:
                db.execute('INSERT INTO subjects (name, answer_count) VALUES (?, ?)', (name, answer_count))
                db.commit()
                flash(f"Предмет '{name}' добавлен", "success")
                return redirect(url_for('subjects.index'))
            except:
                flash("Такой предмет уже существует", "danger")
            finally:
                db.close()
    return render_template('subjects/form.html', subject=None)

@subjects_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    db = get_db_connection()
    subject = db.execute('SELECT * FROM subjects WHERE id = ?', (id,)).fetchone()

    if request.method == 'POST':
        name = request.form['name'].strip()
        answer_count = request.form.get('answer_count', 4, type=int)
        db.execute('UPDATE subjects SET name = ?, answer_count = ? WHERE id = ?', (name, answer_count, id))
        db.commit()
        db.close()
        flash("Предмет обновлён", "success")
        return redirect(url_for('subjects.index'))

    db.close()
    return render_template('subjects/form.html', subject=subject)

@subjects_bp.route('/toggle/<int:id>', methods=['POST'])
@login_required
def toggle(id):
    db = get_db_connection()
    # Меняем значение на противоположное (1 - 0 = 1, 1 - 1 = 0)
    db.execute('UPDATE subjects SET is_active = 1 - is_active WHERE id = ?', (id,))
    db.commit()
    db.close()
    flash("Статус предмета изменен", "info")
    return redirect(url_for('subjects.index'))