import os
import sqlite3
from uuid import uuid4

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from werkzeug.utils import secure_filename

from database import get_db_connection

questions_bp = Blueprint('questions', __name__)

OPTION_KEYS = ('a', 'b', 'c', 'd', 'e')
DIFFICULTY_CHOICES = ('easy', 'hard')
DIFFICULTY_LABELS = {'easy': 'Лёгкий', 'hard': 'Сложный'}


def _project_root() -> str:
    # routes/ -> project root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _save_image(file_storage, rel_dir: str) -> str | None:
    """
    Сохраняет загруженный файл в `static/<rel_dir>/...` и возвращает путь относительно static.
    Возвращает None, если файл не загружен.
    """
    if not file_storage or not getattr(file_storage, 'filename', None):
        return None
    if file_storage.filename == '':
        return None

    static_dir = os.path.join(_project_root(), 'static')
    abs_dir = os.path.join(static_dir, rel_dir)
    _ensure_dir(abs_dir)

    original_ext = os.path.splitext(file_storage.filename)[1].lower()
    if not original_ext:
        original_ext = '.img'

    filename = secure_filename(f'{uuid4().hex}{original_ext}')
    abs_path = os.path.join(abs_dir, filename)
    file_storage.save(abs_path)

    # Для url_for('static', filename=...) нужно относительный путь к static с `/`
    return os.path.join(rel_dir, filename).replace('\\', '/')


def _load_question(db, question_id: int):
    question = db.execute('SELECT * FROM questions WHERE id = ?', (question_id,)).fetchone()
    if not question:
        return None, None

    options_rows = db.execute(
        'SELECT option_key, option_text, option_image FROM question_options WHERE question_id = ?',
        (question_id,),
    ).fetchall()
    options = {row['option_key']: dict(row) for row in options_rows}

    # Чтобы шаблон мог безопасно обращаться к A/B/C/D/E
    for k in OPTION_KEYS:
        options.setdefault(k, {'option_key': k, 'option_text': None, 'option_image': None})

    return question, options


def _load_subjects_for_dropdown(db, current_subject_id: int | None = None):
    # Для формы создаем список с учетом текущего предмета даже если он заблокирован
    active_subjects = db.execute(
        'SELECT id, name, is_active FROM subjects WHERE is_active = 1 ORDER BY name ASC'
    ).fetchall()
    if current_subject_id is not None and active_subjects:
        current = db.execute(
            'SELECT id, name, is_active FROM subjects WHERE id = ?',
            (current_subject_id,),
        ).fetchone()
        if current and not any(s['id'] == current['id'] for s in active_subjects):
            active_subjects = list(active_subjects) + [current]
            active_subjects.sort(key=lambda s: s['name'])

    if not active_subjects:
        # Если активных нет (например, пустая БД), показываем все для удобства отладки
        active_subjects = db.execute('SELECT id, name, is_active FROM subjects ORDER BY name ASC').fetchall()

    return active_subjects


@questions_bp.route('/')
@login_required
def index():
    db = get_db_connection()
    rows = db.execute(
        '''
        SELECT
            q.id,
            q.is_active,
            q.subject_id,
            s.name AS subject_name,
            q.question_text,
            q.question_image,
            q.correct_option,
            q.difficulty
        FROM questions q
        JOIN subjects s ON q.subject_id = s.id
        ORDER BY s.name ASC, q.id DESC
        '''
    ).fetchall()
    db.close()
    return render_template('questions/list.html', questions=rows, difficulty_labels=DIFFICULTY_LABELS)


@questions_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        db = get_db_connection()

        subject_id_raw = request.form.get('subject_id')
        try:
            subject_id = int(subject_id_raw)
        except (TypeError, ValueError):
            subject_id = None

        subject = None
        if subject_id is not None:
            subject = db.execute('SELECT id, is_active FROM subjects WHERE id = ?', (subject_id,)).fetchone()
        if not subject or subject['is_active'] != 1:
            db.close()
            flash('Выбранный предмет неактивен или не найден', 'danger')
            subjects = db.execute('SELECT id, name, is_active FROM subjects ORDER BY name ASC').fetchall()
            return render_template(
                'questions/form.html',
                question=None,
                options={k: {'option_key': k, 'option_text': None, 'option_image': None} for k in OPTION_KEYS},
                subjects=subjects,
                draft={'question_text': request.form.get('question_text', ''), 'correct_option': request.form.get('correct_option'), 'difficulty': request.form.get('difficulty', 'easy')},
                current_subject_id=subject_id,
                option_keys=OPTION_KEYS,
                difficulty_choices=DIFFICULTY_CHOICES,
                difficulty_labels=DIFFICULTY_LABELS,
            )

        question_text = request.form.get('question_text', '').strip() or None
        correct_option = request.form.get('correct_option')
        difficulty = request.form.get('difficulty', 'easy')
        if difficulty not in DIFFICULTY_CHOICES:
            difficulty = 'easy'

        if correct_option not in OPTION_KEYS:
            db.close()
            flash('Неверно указан правильный вариант', 'danger')
            subjects = db.execute('SELECT id, name, is_active FROM subjects ORDER BY name ASC').fetchall()
            return render_template(
                'questions/form.html',
                question=None,
                options={k: {'option_key': k, 'option_text': request.form.get(f'option_{k}_text', '').strip() or None, 'option_image': None} for k in OPTION_KEYS},
                subjects=subjects,
                draft={'question_text': question_text or '', 'correct_option': correct_option, 'difficulty': difficulty},
                current_subject_id=subject_id,
                option_keys=OPTION_KEYS,
                difficulty_choices=DIFFICULTY_CHOICES,
                difficulty_labels=DIFFICULTY_LABELS,
            )

        question_image_file = request.files.get('question_image')

        has_question_image_new = bool(question_image_file and question_image_file.filename)
        if not question_text and not has_question_image_new:
            subjects = _load_subjects_for_dropdown(db, current_subject_id=subject_id)
            db.close()
            flash('У вопроса должен быть текст или фотография', 'danger')
            options_draft = {
                k: {'option_key': k, 'option_text': request.form.get(f'option_{k}_text', '').strip() or None, 'option_image': None}
                for k in OPTION_KEYS
            }
            return render_template(
                'questions/form.html',
                question=None,
                options=options_draft,
                subjects=subjects,
                draft={'question_text': request.form.get('question_text', ''), 'correct_option': correct_option, 'difficulty': difficulty},
                current_subject_id=subject_id,
                option_keys=OPTION_KEYS,
                difficulty_choices=DIFFICULTY_CHOICES,
                difficulty_labels=DIFFICULTY_LABELS,
            )

        # Предварительная валидация вариантов (чтобы не сохранять файлы при ошибках)
        option_final_text = {}
        option_new_files = {}
        option_has_image_new = {}

        errors = []
        for k in OPTION_KEYS:
            opt_text = request.form.get(f'option_{k}_text', '').strip() or None
            opt_file = request.files.get(f'option_{k}_image')
            has_new_image = bool(opt_file and opt_file.filename)

            if not opt_text and not has_new_image:
                errors.append(f'Вариант {k.upper()} должен иметь текст или фотографию')

            option_final_text[k] = opt_text
            option_new_files[k] = opt_file
            option_has_image_new[k] = has_new_image

        if errors:
            subjects = _load_subjects_for_dropdown(db, current_subject_id=subject_id)
            db.close()
            for e in errors:
                flash(e, 'danger')
            options_draft = {
                k: {'option_key': k, 'option_text': option_final_text[k], 'option_image': None}
                for k in OPTION_KEYS
            }
            return render_template(
                'questions/form.html',
                question=None,
                options=options_draft,
                subjects=subjects,
                draft={'question_text': request.form.get('question_text', ''), 'correct_option': correct_option, 'difficulty': difficulty},
                current_subject_id=subject_id,
                option_keys=OPTION_KEYS,
                difficulty_choices=DIFFICULTY_CHOICES,
                difficulty_labels=DIFFICULTY_LABELS,
            )

        # После успешной валидации сохраняем изображения
        question_image_path = _save_image(question_image_file, os.path.join('uploads', 'questions'))
        option_image_paths = {}
        for k in OPTION_KEYS:
            option_image_paths[k] = _save_image(option_new_files[k], os.path.join('uploads', 'questions'))

        try:
            cursor = db.cursor()
            cursor.execute(
                '''
                INSERT INTO questions (subject_id, question_text, question_image, correct_option, difficulty)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (subject_id, question_text, question_image_path, correct_option, difficulty),
            )
            question_id = cursor.lastrowid

            for k in OPTION_KEYS:
                cursor.execute(
                    '''
                    INSERT INTO question_options (question_id, option_key, option_text, option_image)
                    VALUES (?, ?, ?, ?)
                    ''',
                    (question_id, k, option_final_text[k], option_image_paths[k]),
                )
            db.commit()
            db.close()
            flash('Вопрос успешно добавлен', 'success')
            return redirect(url_for('questions.index'))
        except sqlite3.IntegrityError:
            db.rollback()
            db.close()
            flash('Ошибка сохранения: проверьте значения поля(ей)', 'danger')

    db = get_db_connection()
    subjects = _load_subjects_for_dropdown(db)
    db.close()
    options = {k: {'option_key': k, 'option_text': None, 'option_image': None} for k in OPTION_KEYS}
    return render_template(
        'questions/form.html',
        question=None,
        options=options,
        subjects=subjects,
        draft={'question_text': '', 'correct_option': 'a', 'difficulty': 'easy'},
        current_subject_id=None,
        option_keys=OPTION_KEYS,
        difficulty_choices=DIFFICULTY_CHOICES,
        difficulty_labels=DIFFICULTY_LABELS,
    )


@questions_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id: int):
    db = get_db_connection()
    question, options = _load_question(db, id)
    if not question:
        db.close()
        flash('Вопрос не найден', 'danger')
        return redirect(url_for('questions.index'))

    if request.method == 'POST':
        subject_id_raw = request.form.get('subject_id')
        try:
            subject_id = int(subject_id_raw)
        except (TypeError, ValueError):
            subject_id = None

        subject = None
        if subject_id is not None:
            subject = db.execute('SELECT id FROM subjects WHERE id = ?', (subject_id,)).fetchone()
        if not subject:
            subjects = _load_subjects_for_dropdown(db, current_subject_id=question['subject_id'])
            correct_option = request.form.get('correct_option')
            db.close()
            flash('Выбранный предмет не найден', 'danger')
            options_draft = {}
            for k in OPTION_KEYS:
                options_draft[k] = {
                    'option_key': k,
                    'option_text': request.form.get(f'option_{k}_text', '').strip() or None,
                    'option_image': options[k].get('option_image'),
                }
            return render_template(
                'questions/form.html',
                question=question,
                options=options_draft,
                subjects=subjects,
                draft={'question_text': request.form.get('question_text', ''), 'correct_option': correct_option, 'difficulty': request.form.get('difficulty', 'easy')},
                current_subject_id=question['subject_id'],
                option_keys=OPTION_KEYS,
                difficulty_choices=DIFFICULTY_CHOICES,
                difficulty_labels=DIFFICULTY_LABELS,
            )

        question_text = request.form.get('question_text', '').strip() or None
        correct_option = request.form.get('correct_option')
        difficulty = request.form.get('difficulty', 'easy')
        if difficulty not in DIFFICULTY_CHOICES:
            difficulty = 'easy'

        if correct_option not in OPTION_KEYS:
            subjects = _load_subjects_for_dropdown(db, current_subject_id=question['subject_id'])
            db.close()
            flash('Неверно указан правильный вариант', 'danger')
            options_draft = {}
            for k in OPTION_KEYS:
                options_draft[k] = {
                    'option_key': k,
                    'option_text': request.form.get(f'option_{k}_text', '').strip() or None,
                    'option_image': options[k].get('option_image'),
                }
            return render_template(
                'questions/form.html',
                question=question,
                options=options_draft,
                subjects=subjects,
                draft={'question_text': request.form.get('question_text', ''), 'correct_option': correct_option, 'difficulty': difficulty},
                current_subject_id=question['subject_id'],
                option_keys=OPTION_KEYS,
                difficulty_choices=DIFFICULTY_CHOICES,
                difficulty_labels=DIFFICULTY_LABELS,
            )

        # Новые файлы (если загружены)
        question_image_file = request.files.get('question_image')
        has_new_question_image = bool(question_image_file and question_image_file.filename)

        # Валидация вопроса (должно быть текст или картинка, с учетом существующих значений)
        final_question_image_present = has_new_question_image or bool(question['question_image'])
        if not question_text and not final_question_image_present:
            subjects = _load_subjects_for_dropdown(db, current_subject_id=question['subject_id'])
            db.close()
            flash('У вопроса должен быть текст или фотография', 'danger')
            options_draft = {
                k: {
                    'option_key': k,
                    'option_text': request.form.get(f'option_{k}_text', '').strip() or None,
                    'option_image': options[k].get('option_image'),
                }
                for k in OPTION_KEYS
            }
            return render_template(
                'questions/form.html',
                question=question,
                options=options_draft,
                subjects=subjects,
                draft={'question_text': request.form.get('question_text', ''), 'correct_option': correct_option, 'difficulty': difficulty},
                current_subject_id=question['subject_id'],
                option_keys=OPTION_KEYS,
                difficulty_choices=DIFFICULTY_CHOICES,
                difficulty_labels=DIFFICULTY_LABELS,
            )

        # Валидация вариантов
        new_option_files = {}
        final_option_text = {}
        final_option_image_paths = {}
        errors = []
        for k in OPTION_KEYS:
            opt_text = request.form.get(f'option_{k}_text', '').strip() or None
            opt_file = request.files.get(f'option_{k}_image')
            has_new_image = bool(opt_file and opt_file.filename)
            existing_image = options[k].get('option_image')

            final_has_image = has_new_image or bool(existing_image)
            if not opt_text and not final_has_image:
                errors.append(f'Вариант {k.upper()} должен иметь текст или фотографию')

            final_option_text[k] = opt_text
            new_option_files[k] = opt_file
            final_option_image_paths[k] = options[k].get('option_image')  # если файл не загружен, оставляем

        if errors:
            subjects = _load_subjects_for_dropdown(db, current_subject_id=question['subject_id'])
            db.close()
            for e in errors:
                flash(e, 'danger')
            options_draft = {
                k: {
                    'option_key': k,
                    'option_text': final_option_text[k],
                    'option_image': options[k].get('option_image'),
                }
                for k in OPTION_KEYS
            }
            return render_template(
                'questions/form.html',
                question=question,
                options=options_draft,
                subjects=subjects,
                draft={'question_text': request.form.get('question_text', ''), 'correct_option': correct_option, 'difficulty': difficulty},
                current_subject_id=question['subject_id'],
                option_keys=OPTION_KEYS,
                difficulty_choices=DIFFICULTY_CHOICES,
                difficulty_labels=DIFFICULTY_LABELS,
            )

        # Сохраняем новые изображения
        new_question_image_path = None
        if has_new_question_image:
            new_question_image_path = _save_image(question_image_file, os.path.join('uploads', 'questions'))

        for k in OPTION_KEYS:
            has_new_image = bool(new_option_files[k] and new_option_files[k].filename)
            if has_new_image:
                final_option_image_paths[k] = _save_image(new_option_files[k], os.path.join('uploads', 'questions'))

        try:
            db.execute(
                '''
                UPDATE questions
                SET subject_id = ?, question_text = ?, question_image = ?, correct_option = ?, difficulty = ?
                WHERE id = ?
                ''',
                (subject_id, question_text, new_question_image_path if new_question_image_path is not None else question['question_image'], correct_option, difficulty, id),
            )

            for k in OPTION_KEYS:
                # UPSERT: чтобы не зависеть от rowcount (SQLite rowcount может быть 0 даже при существующей строке)
                db.execute(
                    '''
                    INSERT INTO question_options (question_id, option_key, option_text, option_image)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(question_id, option_key)
                    DO UPDATE SET
                        option_text = excluded.option_text,
                        option_image = excluded.option_image
                    ''',
                    (id, k, final_option_text[k], final_option_image_paths[k]),
                )

            db.commit()
            db.close()
            flash('Вопрос успешно обновлен', 'success')
            return redirect(url_for('questions.index'))
        except sqlite3.IntegrityError:
            db.rollback()
            db.close()
            flash('Ошибка сохранения: проверьте значения полей', 'danger')

    subjects = _load_subjects_for_dropdown(db, current_subject_id=question['subject_id'])
    db.close()
    return render_template(
        'questions/form.html',
        question=question,
        options=options,
        subjects=subjects,
        draft={'question_text': '', 'correct_option': question['correct_option'], 'difficulty': question['difficulty']},
        current_subject_id=question['subject_id'],
        option_keys=OPTION_KEYS,
        difficulty_choices=DIFFICULTY_CHOICES,
        difficulty_labels=DIFFICULTY_LABELS,
    )


@questions_bp.route('/toggle/<int:id>', methods=['POST'])
@login_required
def toggle(id: int):
    db = get_db_connection()
    db.execute('UPDATE questions SET is_active = 1 - is_active WHERE id = ?', (id,))
    db.commit()
    db.close()
    flash('Статус вопроса изменен', 'info')
    return redirect(url_for('questions.index'))

