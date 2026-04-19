import io
import json
import os
import random
import sqlite3

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import login_required

from database import get_db_connection

tests_bp = Blueprint('tests', __name__)

FONT_REGULAR = r'C:\Windows\Fonts\arial.ttf'
FONT_BOLD = r'C:\Windows\Fonts\arialbd.ttf'


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _get_active_subjects(db):
    return db.execute(
        'SELECT id, name FROM subjects WHERE is_active = 1 ORDER BY name ASC'
    ).fetchall()


def _parse_subject_rows(form):
    subject_ids = request.form.getlist('subject_id')
    question_counts = request.form.getlist('question_count')
    rows = []
    for sid, qc in zip(subject_ids, question_counts):
        try:
            sid = int(sid)
            qc = int(qc)
        except (TypeError, ValueError):
            continue
        rows.append({'subject_id': sid, 'question_count': qc})
    return rows


def _validate_rows(db, rows, total_questions):
    errors = []
    if not rows:
        errors.append('Добавьте хотя бы один предмет.')
        return errors

    seen = set()
    for r in rows:
        if r['subject_id'] in seen:
            errors.append('Один и тот же предмет указан несколько раз.')
            break
        seen.add(r['subject_id'])
        if r['question_count'] <= 0:
            errors.append('Количество вопросов должно быть больше 0.')

    total = sum(r['question_count'] for r in rows)
    if total != total_questions:
        errors.append(
            f'Сумма вопросов по предметам ({total}) должна равняться '
            f'общему количеству вопросов ({total_questions}).'
        )

    valid_ids = {r['id'] for r in db.execute(
        'SELECT id FROM subjects WHERE is_active = 1'
    ).fetchall()}
    for r in rows:
        if r['subject_id'] not in valid_ids:
            errors.append(f'Предмет с ID {r["subject_id"]} не найден или неактивен.')

    return errors


def _calc_feasible_max(easy_available: int, hard_available: int, easy_percent: int) -> int:
    total_avail = easy_available + hard_available
    if total_avail == 0:
        return 0
    max_feasible = 0
    for n in range(1, total_avail + 1):
        easy_need = round(n * easy_percent / 100)
        hard_need = n - easy_need
        if easy_need <= easy_available and hard_need <= hard_available:
            max_feasible = n
    return max_feasible


def _check_availability(db, rows, easy_percent):
    errors = []
    for r in rows:
        easy_avail = db.execute(
            "SELECT COUNT(*) FROM questions WHERE subject_id = ? AND difficulty = 'easy' AND is_active = 1",
            (r['subject_id'],),
        ).fetchone()[0]
        hard_avail = db.execute(
            "SELECT COUNT(*) FROM questions WHERE subject_id = ? AND difficulty = 'hard' AND is_active = 1",
            (r['subject_id'],),
        ).fetchone()[0]
        max_feasible = _calc_feasible_max(easy_avail, hard_avail, easy_percent)
        if r['question_count'] > max_feasible:
            subject_name = db.execute(
                'SELECT name FROM subjects WHERE id = ?', (r['subject_id'],)
            ).fetchone()['name']
            easy_need = round(r['question_count'] * easy_percent / 100)
            hard_need = r['question_count'] - easy_need
            errors.append(
                f'Предмет «{subject_name}»: запрошено {r["question_count"]} вопросов '
                f'(лёгких: {easy_need}, сложных: {hard_need}), '
                f'но доступно только лёгких: {easy_avail}, сложных: {hard_avail} '
                f'(максимум для данного соотношения: {max_feasible}).'
            )
    return errors


# ─────────────────────────────────────────────────────────────────────────────
# PDF Generation
# ─────────────────────────────────────────────────────────────────────────────

def _generate_pdf(test: dict, questions_with_options: list, static_dir: str) -> bytes:
    """
    questions_with_options: list of (question_dict, options_dict, active_keys_tuple)
    """
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    pdf.add_font('Arial', '', FONT_REGULAR)
    pdf.add_font('Arial', 'B', FONT_BOLD)

    pdf.add_page()

    pdf.set_font('Arial', 'B', 20)
    pdf.cell(0, 14, text=test['name'], align='C', new_x='LMARGIN', new_y='NEXT')

    easy = test['easy_percent']
    hard = 100 - easy
    pdf.set_font('Arial', '', 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(
        0, 8,
        text=f"Всего вопросов: {test['total_questions']}   |   "
             f"Лёгкие: {easy}%   Сложные: {hard}%",
        align='C',
        new_x='LMARGIN', new_y='NEXT',
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    pdf.set_draw_color(80, 80, 200)
    pdf.set_line_width(0.8)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.set_draw_color(180, 180, 180)
    pdf.ln(8)

    for i, (question, options, active_keys) in enumerate(questions_with_options, 1):
        has_imgs = bool(question.get('question_image')) or any(
            opt.get('option_image')
            for opt in options.values()
            if opt.get('option_image')
        )

        if has_imgs:
            pdf.add_page()

        pdf.set_font('Arial', 'B', 12)
        q_text = question.get('question_text') or ''
        if q_text:
            pdf.multi_cell(0, 8, text=f"{i}. {q_text}", new_x='LMARGIN', new_y='NEXT')
        else:
            pdf.multi_cell(0, 8, text=f"{i}.", new_x='LMARGIN', new_y='NEXT')

        if question.get('question_image'):
            img_path = os.path.join(
                static_dir, question['question_image'].replace('/', os.sep)
            )
            if os.path.exists(img_path):
                avail_w = pdf.w - pdf.l_margin - pdf.r_margin
                img_w = min(avail_w * 0.65, 130)
                pdf.image(img_path, x=pdf.l_margin + 8, w=img_w)
                pdf.ln(3)

        pdf.set_font('Arial', '', 11)
        for opt_key in active_keys:
            opt = options.get(opt_key, {})
            opt_text = opt.get('option_text') or ''
            opt_image = opt.get('option_image')

            if opt_text:
                pdf.multi_cell(
                    0, 7,
                    text=f"    {opt_key.upper()})  {opt_text}",
                    new_x='LMARGIN', new_y='NEXT',
                )
            else:
                pdf.cell(0, 7, text=f"    {opt_key.upper()})", new_x='LMARGIN', new_y='NEXT')

            if opt_image:
                img_path = os.path.join(
                    static_dir, opt_image.replace('/', os.sep)
                )
                if os.path.exists(img_path):
                    pdf.image(img_path, x=pdf.l_margin + 20, w=70)
                    pdf.ln(2)

        pdf.ln(4)
        if not has_imgs:
            pdf.set_draw_color(180, 180, 180)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(5)

    return bytes(pdf.output())


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@tests_bp.route('/api/subject-stats')
@login_required
def subject_stats():
    subject_id = request.args.get('subject_id', type=int)
    easy_percent = request.args.get('easy_percent', type=int, default=50)

    if not subject_id:
        return jsonify({'error': 'subject_id required'}), 400

    db = get_db_connection()
    easy_avail = db.execute(
        "SELECT COUNT(*) FROM questions WHERE subject_id = ? AND difficulty = 'easy' AND is_active = 1",
        (subject_id,),
    ).fetchone()[0]
    hard_avail = db.execute(
        "SELECT COUNT(*) FROM questions WHERE subject_id = ? AND difficulty = 'hard' AND is_active = 1",
        (subject_id,),
    ).fetchone()[0]
    db.close()

    max_feasible = _calc_feasible_max(easy_avail, hard_avail, easy_percent)
    return jsonify({
        'easy_available': easy_avail,
        'hard_available': hard_avail,
        'max_feasible': max_feasible,
    })


@tests_bp.route('/')
@login_required
def index():
    db = get_db_connection()
    tests = db.execute(
        '''
        SELECT
            t.id, t.name, t.total_questions, t.easy_percent,
            COUNT(ts.id) AS subject_count
        FROM tests t
        LEFT JOIN test_subjects ts ON ts.test_id = t.id
        GROUP BY t.id
        ORDER BY t.id DESC
        '''
    ).fetchall()
    db.close()
    return render_template('tests/list.html', tests=tests)


@tests_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    db = get_db_connection()
    subjects = _get_active_subjects(db)
    subjects_json = json.dumps([{'id': s['id'], 'name': s['name']} for s in subjects])

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        try:
            total_questions = int(request.form.get('total_questions', 0))
        except (TypeError, ValueError):
            total_questions = 0
        try:
            easy_percent = int(request.form.get('easy_percent', 50))
        except (TypeError, ValueError):
            easy_percent = 50

        rows = _parse_subject_rows(request.form)

        errors = []
        if not name:
            errors.append('Укажите наименование теста.')
        if total_questions <= 0:
            errors.append('Общее количество вопросов должно быть больше 0.')
        if not (0 <= easy_percent <= 100):
            errors.append('Процент лёгких вопросов должен быть от 0 до 100.')
        if not errors:
            errors.extend(_validate_rows(db, rows, total_questions))
        if not errors:
            errors.extend(_check_availability(db, rows, easy_percent))

        if errors:
            db.close()
            for e in errors:
                flash(e, 'danger')
            return render_template(
                'tests/form.html',
                test=None,
                subjects_json=subjects_json,
                subjects=subjects,
                draft={'name': name, 'total_questions': total_questions, 'easy_percent': easy_percent},
                existing_rows=rows,
            )

        try:
            cursor = db.cursor()
            cursor.execute(
                'INSERT INTO tests (name, total_questions, easy_percent) VALUES (?, ?, ?)',
                (name, total_questions, easy_percent),
            )
            test_id = cursor.lastrowid
            for r in rows:
                cursor.execute(
                    'INSERT INTO test_subjects (test_id, subject_id, question_count) VALUES (?, ?, ?)',
                    (test_id, r['subject_id'], r['question_count']),
                )
            db.commit()
            db.close()
            flash('Тест успешно создан', 'success')
            return redirect(url_for('tests.index'))
        except sqlite3.IntegrityError:
            db.rollback()
            db.close()
            flash('Ошибка сохранения: проверьте данные.', 'danger')

    db.close()
    return render_template(
        'tests/form.html',
        test=None,
        subjects_json=subjects_json,
        subjects=subjects,
        draft={'name': '', 'total_questions': '', 'easy_percent': 50},
        existing_rows=[],
    )


@tests_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id: int):
    db = get_db_connection()
    test = db.execute('SELECT * FROM tests WHERE id = ?', (id,)).fetchone()
    if not test:
        db.close()
        flash('Тест не найден', 'danger')
        return redirect(url_for('tests.index'))

    subjects = _get_active_subjects(db)
    subjects_json = json.dumps([{'id': s['id'], 'name': s['name']} for s in subjects])

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        try:
            total_questions = int(request.form.get('total_questions', 0))
        except (TypeError, ValueError):
            total_questions = 0
        try:
            easy_percent = int(request.form.get('easy_percent', 50))
        except (TypeError, ValueError):
            easy_percent = 50

        rows = _parse_subject_rows(request.form)

        errors = []
        if not name:
            errors.append('Укажите наименование теста.')
        if total_questions <= 0:
            errors.append('Общее количество вопросов должно быть больше 0.')
        if not (0 <= easy_percent <= 100):
            errors.append('Процент лёгких вопросов должен быть от 0 до 100.')
        if not errors:
            errors.extend(_validate_rows(db, rows, total_questions))
        if not errors:
            errors.extend(_check_availability(db, rows, easy_percent))

        if errors:
            db.close()
            for e in errors:
                flash(e, 'danger')
            return render_template(
                'tests/form.html',
                test=test,
                subjects_json=subjects_json,
                subjects=subjects,
                draft={'name': name, 'total_questions': total_questions, 'easy_percent': easy_percent},
                existing_rows=rows,
            )

        try:
            db.execute(
                'UPDATE tests SET name = ?, total_questions = ?, easy_percent = ? WHERE id = ?',
                (name, total_questions, easy_percent, id),
            )
            db.execute('DELETE FROM test_subjects WHERE test_id = ?', (id,))
            for r in rows:
                db.execute(
                    'INSERT INTO test_subjects (test_id, subject_id, question_count) VALUES (?, ?, ?)',
                    (id, r['subject_id'], r['question_count']),
                )
            db.commit()
            db.close()
            flash('Тест успешно обновлён', 'success')
            return redirect(url_for('tests.index'))
        except sqlite3.IntegrityError:
            db.rollback()
            db.close()
            flash('Ошибка сохранения: проверьте данные.', 'danger')

    test_subjects = db.execute(
        'SELECT subject_id, question_count FROM test_subjects WHERE test_id = ? ORDER BY id',
        (id,),
    ).fetchall()
    db.close()
    return render_template(
        'tests/form.html',
        test=test,
        subjects_json=subjects_json,
        subjects=subjects,
        draft={
            'name': test['name'],
            'total_questions': test['total_questions'],
            'easy_percent': test['easy_percent'],
        },
        existing_rows=[dict(r) for r in test_subjects],
    )


@tests_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id: int):
    db = get_db_connection()
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('DELETE FROM tests WHERE id = ?', (id,))
    db.commit()
    db.close()
    flash('Тест удалён', 'info')
    return redirect(url_for('tests.index'))


@tests_bp.route('/export/<int:id>/pdf')
@login_required
def export_pdf(id: int):
    db = get_db_connection()
    test = db.execute('SELECT * FROM tests WHERE id = ?', (id,)).fetchone()
    if not test:
        db.close()
        flash('Тест не найден', 'danger')
        return redirect(url_for('tests.index'))

    test_subjects = db.execute(
        '''
        SELECT ts.subject_id, ts.question_count, s.name AS subject_name, s.answer_count
        FROM test_subjects ts
        JOIN subjects s ON s.id = ts.subject_id
        WHERE ts.test_id = ?
        ''',
        (id,),
    ).fetchall()

    easy_percent = test['easy_percent']
    all_questions = []

    for ts in test_subjects:
        q_count = ts['question_count']
        easy_count = round(q_count * easy_percent / 100)
        hard_count = q_count - easy_count
        active_keys = ('a', 'b', 'c', 'd', 'e')[:ts['answer_count']]

        easy_qs = db.execute(
            '''
            SELECT id, question_text, question_image, correct_option, subject_id
            FROM questions
            WHERE subject_id = ? AND difficulty = 'easy' AND is_active = 1
            ORDER BY RANDOM() LIMIT ?
            ''',
            (ts['subject_id'], easy_count),
        ).fetchall()

        hard_qs = db.execute(
            '''
            SELECT id, question_text, question_image, correct_option, subject_id
            FROM questions
            WHERE subject_id = ? AND difficulty = 'hard' AND is_active = 1
            ORDER BY RANDOM() LIMIT ?
            ''',
            (ts['subject_id'], hard_count),
        ).fetchall()

        for q in list(easy_qs) + list(hard_qs):
            all_questions.append((dict(q), active_keys))

    random.shuffle(all_questions)

    questions_with_options = []
    for q_dict, active_keys in all_questions:
        opts = db.execute(
            'SELECT option_key, option_text, option_image FROM question_options WHERE question_id = ?',
            (q_dict['id'],),
        ).fetchall()
        options = {row['option_key']: dict(row) for row in opts}
        for k in ('a', 'b', 'c', 'd', 'e'):
            options.setdefault(k, {'option_key': k, 'option_text': None, 'option_image': None})
        questions_with_options.append((q_dict, options, active_keys))

    # Сохраняем экземпляр теста с выбранными вопросами и правильными ответами
    cursor = db.cursor()
    cursor.execute('INSERT INTO test_instances (test_id) VALUES (?)', (id,))
    instance_id = cursor.lastrowid
    for order, (q_dict, options, active_keys) in enumerate(questions_with_options, 1):
        cursor.execute(
            'INSERT INTO test_instance_questions (instance_id, subject_id, question_id, correct_option, question_order) VALUES (?, ?, ?, ?, ?)',
            (instance_id, q_dict['subject_id'], q_dict['id'], q_dict['correct_option'], order),
        )
    db.commit()
    db.close()

    static_dir = os.path.join(_project_root(), 'static')
    pdf_bytes = _generate_pdf(dict(test), questions_with_options, static_dir)

    safe_name = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in test['name'])
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{safe_name}.pdf',
    )


@tests_bp.route('/<int:test_id>/instances')
@login_required
def instances(test_id: int):
    db = get_db_connection()
    test = db.execute('SELECT * FROM tests WHERE id = ?', (test_id,)).fetchone()
    if not test:
        db.close()
        flash('Тест не найден', 'danger')
        return redirect(url_for('tests.index'))

    instances_list = db.execute(
        '''
        SELECT ti.id, ti.created_at, COUNT(tiq.id) AS question_count
        FROM test_instances ti
        LEFT JOIN test_instance_questions tiq ON tiq.instance_id = ti.id
        WHERE ti.test_id = ?
        GROUP BY ti.id
        ORDER BY ti.id DESC
        ''',
        (test_id,),
    ).fetchall()
    db.close()
    return render_template('tests/instances.html', test=test, instances=instances_list)


@tests_bp.route('/instances/<int:instance_id>')
@login_required
def instance_detail(instance_id: int):
    db = get_db_connection()
    instance = db.execute(
        '''
        SELECT ti.id, ti.created_at, ti.test_id, t.name AS test_name
        FROM test_instances ti
        JOIN tests t ON t.id = ti.test_id
        WHERE ti.id = ?
        ''',
        (instance_id,),
    ).fetchone()
    if not instance:
        db.close()
        flash('Экземпляр теста не найден', 'danger')
        return redirect(url_for('tests.index'))

    rows = db.execute(
        '''
        SELECT
            tiq.question_order,
            tiq.correct_option,
            tiq.subject_id,
            s.name AS subject_name,
            s.answer_count,
            q.question_text,
            q.question_image,
            q.difficulty,
            tiq.question_id
        FROM test_instance_questions tiq
        JOIN subjects s ON s.id = tiq.subject_id
        JOIN questions q ON q.id = tiq.question_id
        WHERE tiq.instance_id = ?
        ORDER BY tiq.question_order ASC
        ''',
        (instance_id,),
    ).fetchall()

    # Загружаем варианты ответов для каждого вопроса
    questions = []
    for row in rows:
        opts = db.execute(
            'SELECT option_key, option_text, option_image FROM question_options WHERE question_id = ?',
            (row['question_id'],),
        ).fetchall()
        options = {o['option_key']: dict(o) for o in opts}
        active_keys = ('a', 'b', 'c', 'd', 'e')[:row['answer_count']]
        correct_list = row['correct_option'].split(',')
        questions.append({
            'order': row['question_order'],
            'subject_name': row['subject_name'],
            'subject_id': row['subject_id'],
            'question_text': row['question_text'],
            'question_image': row['question_image'],
            'difficulty': row['difficulty'],
            'correct_list': correct_list,
            'active_keys': active_keys,
            'options': options,
        })

    # Группируем по предмету
    subjects_map = {}
    for q in questions:
        sid = q['subject_id']
        if sid not in subjects_map:
            subjects_map[sid] = {'name': q['subject_name'], 'questions': []}
        subjects_map[sid]['questions'].append(q)

    db.close()
    return render_template(
        'tests/instance_detail.html',
        instance=instance,
        subjects=list(subjects_map.values()),
        all_questions=questions,
    )


@tests_bp.route('/instances/<int:instance_id>/delete', methods=['POST'])
@login_required
def instance_delete(instance_id: int):
    db = get_db_connection()
    instance = db.execute('SELECT test_id FROM test_instances WHERE id = ?', (instance_id,)).fetchone()
    if instance:
        test_id = instance['test_id']
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('DELETE FROM test_instances WHERE id = ?', (instance_id,))
        db.commit()
        db.close()
        flash('Экземпляр теста удалён', 'info')
        return redirect(url_for('tests.instances', test_id=test_id))
    db.close()
    flash('Экземпляр не найден', 'danger')
    return redirect(url_for('tests.index'))
