from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from database import get_db_connection

classrooms_bp = Blueprint('classrooms', __name__)


@classrooms_bp.route('/')
@login_required
def index():
    db = get_db_connection()
    classrooms = db.execute('SELECT * FROM classrooms ORDER BY name ASC').fetchall()
    db.close()
    return render_template('classrooms/list.html', classrooms=classrooms)


@classrooms_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        location = request.form.get('location', '').strip()
        try:
            capacity = int(request.form.get('capacity', 0))
        except (TypeError, ValueError):
            capacity = 0

        if not name:
            flash('Наименование не может быть пустым', 'danger')
        elif not location:
            flash('Место размещения не может быть пустым', 'danger')
        elif capacity <= 0:
            flash('Вместимость должна быть больше 0', 'danger')
        else:
            db = get_db_connection()
            try:
                db.execute(
                    'INSERT INTO classrooms (name, location, capacity) VALUES (?, ?, ?)',
                    (name, location, capacity),
                )
                db.commit()
                flash(f"Класс «{name}» добавлен", 'success')
                return redirect(url_for('classrooms.index'))
            except Exception:
                flash('Класс с таким наименованием уже существует', 'danger')
            finally:
                db.close()
    return render_template('classrooms/form.html', classroom=None)


@classrooms_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    db = get_db_connection()
    classroom = db.execute('SELECT * FROM classrooms WHERE id = ?', (id,)).fetchone()
    if not classroom:
        db.close()
        flash('Класс не найден', 'danger')
        return redirect(url_for('classrooms.index'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        location = request.form.get('location', '').strip()
        try:
            capacity = int(request.form.get('capacity', 0))
        except (TypeError, ValueError):
            capacity = 0

        if not name:
            flash('Наименование не может быть пустым', 'danger')
        elif not location:
            flash('Место размещения не может быть пустым', 'danger')
        elif capacity <= 0:
            flash('Вместимость должна быть больше 0', 'danger')
        else:
            db.execute(
                'UPDATE classrooms SET name = ?, location = ?, capacity = ? WHERE id = ?',
                (name, location, capacity, id),
            )
            db.commit()
            db.close()
            flash('Класс обновлён', 'success')
            return redirect(url_for('classrooms.index'))

    db.close()
    return render_template('classrooms/form.html', classroom=classroom)


@classrooms_bp.route('/toggle/<int:id>', methods=['POST'])
@login_required
def toggle(id):
    db = get_db_connection()
    db.execute('UPDATE classrooms SET is_active = 1 - is_active WHERE id = ?', (id,))
    db.commit()
    db.close()
    flash('Статус класса изменён', 'info')
    return redirect(url_for('classrooms.index'))


@classrooms_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    db = get_db_connection()
    classroom = db.execute('SELECT name FROM classrooms WHERE id = ?', (id,)).fetchone()
    if classroom:
        db.execute('DELETE FROM classrooms WHERE id = ?', (id,))
        db.commit()
        flash(f"Класс «{classroom['name']}» удалён", 'info')
    db.close()
    return redirect(url_for('classrooms.index'))
