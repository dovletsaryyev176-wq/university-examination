import io
import json
import os
import random
import sqlite3

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import login_required

from database import get_db_connection

tests_bp = Blueprint('tests', __name__)


def _find_font(bold=False):
    if bold:
        candidates = [
            r'C:\Windows\Fonts\arialbd.ttf',
            '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
            '/Library/Fonts/Arial Bold.ttf',
            '/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/liberation/LiberationSans-Bold.ttf',
        ]
    else:
        candidates = [
            r'C:\Windows\Fonts\ARIALUNI.TTF',
            r'C:\Windows\Fonts\arial.ttf',
            '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
            '/System/Library/Fonts/Supplemental/Arial.ttf',
            '/Library/Fonts/Arial Unicode.ttf',
            '/Library/Fonts/Arial.ttf',
            '/usr/share/fonts/truetype/msttcorefonts/Arial.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/liberation/LiberationSans-Regular.ttf',
        ]
    return next((p for p in candidates if os.path.exists(p)), None)


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
        errors.append('Iň bolmanda bir ders goşuň.')
        return errors

    seen = set()
    for r in rows:
        if r['subject_id'] in seen:
            errors.append('Bir ders birnäçe gezek görkezilen.')
            break
        seen.add(r['subject_id'])
        if r['question_count'] <= 0:
            errors.append('Sorag sany 0-dan uly bolmaly.')

    total = sum(r['question_count'] for r in rows)
    if total != total_questions:
        errors.append(
            f'Dersler boýunça soraglaryň jemi ({total}) deň bolmaly '
            f'umumy soraglaryň sanyna ({total_questions}).'
        )

    valid_ids = {r['id'] for r in db.execute(
        'SELECT id FROM subjects WHERE is_active = 1'
    ).fetchall()}
    for r in rows:
        if r['subject_id'] not in valid_ids:
            errors.append(f'ID we dersi {r["subject_id"]} tapylmady ýa-da bloklanan.')

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
                f'Ders «{subject_name}»: soralan sorag {r["question_count"]} sany '
                f'(ýönekeý: {easy_need}, çylşyrymly: {hard_need}), '
                f'emma ýönekeý bar: {easy_avail}, çylşyrymly: {hard_avail} '
                f'(maksimum bu bölünişik boýunça: {max_feasible}).'
            )
    return errors


def _pdf_add_text(pdf, text: str, font_name: str = 'Helvetica',
                  x_offset: float = 0, bold: bool = False,
                  fontsize: int = 12, line_h: int = 8) -> None:
    avail_w = pdf.w - pdf.l_margin - pdf.r_margin - x_offset
    font_style = 'B' if bold else ''
    pdf.set_font(font_name, font_style, fontsize)
    if x_offset:
        pdf.set_x(pdf.l_margin + x_offset)
    pdf.multi_cell(avail_w, line_h, text=text, new_x='LMARGIN', new_y='NEXT')


_IMG_W_MM = 65
_IMG_H_MM = 50
_IMG_DPI  = 150

_IMG_W_PX = int(_IMG_W_MM * _IMG_DPI / 25.4)
_IMG_H_PX = int(_IMG_H_MM * _IMG_DPI / 25.4)

_OPT_IMG_W_MM = _IMG_W_MM
_OPT_IMG_H_MM = _IMG_H_MM


def _letterbox_image(img_path: str) -> io.BytesIO:
    from PIL import Image
    img = Image.open(img_path).convert('RGB')
    img.thumbnail((_IMG_W_PX, _IMG_H_PX), Image.LANCZOS)
    canvas = Image.new('RGB', (_IMG_W_PX, _IMG_H_PX), (255, 255, 255))
    x_off = (_IMG_W_PX - img.width) // 2
    y_off = (_IMG_H_PX - img.height) // 2
    canvas.paste(img, (x_off, y_off))
    buf = io.BytesIO()
    canvas.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _generate_pdf(test: dict, questions_with_options: list, static_dir: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    font_name = 'Helvetica'
    reg = _find_font(bold=False)
    bld = _find_font(bold=True)
    if reg:
        try:
            pdf.add_font('Arial', '', reg)
            pdf.add_font('Arial', 'B', bld or reg)
            font_name = 'Arial'
        except Exception:
            pass

    pdf.add_page()

    pdf.set_font(font_name, 'B', 20)
    pdf.cell(0, 14, text=test['name'], align='C', new_x='LMARGIN', new_y='NEXT')

    easy = test['easy_percent']
    hard = 100 - easy
    pdf.set_font(font_name, '', 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(
        0, 8,
        text=f"Jemi sorag sany: {test['total_questions']}   |   "
             f"Ýönekeý: {easy}%   Çylşyrymly: {hard}%",
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

    current_subject = None
    subject_q_num = 0

    for i, (question, options, active_keys, subject_name) in enumerate(questions_with_options, 1):
        if subject_name != current_subject:
            current_subject = subject_name
            subject_q_num = 0
            pdf.set_font(font_name, 'B', 13)
            pdf.set_fill_color(220, 232, 255)
            pdf.set_text_color(30, 60, 140)
            pdf.cell(0, 9, text=subject_name, border=0, fill=True,
                     new_x='LMARGIN', new_y='NEXT')
            pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

        subject_q_num += 1

        has_imgs = bool(question.get('question_image')) or any(
            opt.get('option_image')
            for opt in options.values()
            if opt.get('option_image')
        )

        if has_imgs:
            pdf.add_page()

        q_text = question.get('question_text') or ''
        pdf.set_font(font_name, 'B', 12)
        num_label = f"{subject_q_num}."
        num_w = 10
        if q_text:
            pdf.cell(num_w, 8, text=num_label, new_x='RIGHT', new_y='TOP')
            avail_w = pdf.w - pdf.l_margin - pdf.r_margin - num_w
            pdf.multi_cell(avail_w, 8, text=q_text, new_x='LMARGIN', new_y='NEXT')
        else:
            pdf.cell(0, 8, text=num_label, new_x='LMARGIN', new_y='NEXT')

        if question.get('question_image'):
            img_path = os.path.join(
                static_dir, question['question_image'].replace('/', os.sep)
            )
            if os.path.exists(img_path):
                pdf.image(
                    _letterbox_image(img_path),
                    x=pdf.l_margin + 8,
                    w=_IMG_W_MM,
                    h=_IMG_H_MM,
                )
                pdf.ln(3)

        pdf.set_font(font_name, '', 11)
        for opt_key in active_keys:
            opt = options.get(opt_key, {})
            opt_text = opt.get('option_text') or ''
            opt_image = opt.get('option_image')

            label = f"{opt_key.upper()}) "
            if opt_text:
                full_text = label + opt_text
                _pdf_add_text(pdf, full_text, font_name=font_name, x_offset=8, bold=False, fontsize=11, line_h=7)
            else:
                pdf.set_font(font_name, '', 11)
                pdf.set_x(pdf.l_margin + 8)
                pdf.cell(0, 7, text=label, new_x='LMARGIN', new_y='NEXT')

            if opt_image:
                img_path = os.path.join(
                    static_dir, opt_image.replace('/', os.sep)
                )
                if os.path.exists(img_path):
                    pdf.image(
                        _letterbox_image(img_path),
                        x=pdf.l_margin + 20,
                        w=_OPT_IMG_W_MM,
                        h=_OPT_IMG_H_MM,
                    )
                    pdf.ln(2)

        pdf.ln(4)
        if not has_imgs:
            pdf.set_draw_color(180, 180, 180)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(5)

    return bytes(pdf.output())


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
            errors.append('Testiň adyny giriziň.')
        if total_questions <= 0:
            errors.append('Umumy sorag sany 0-dan uly bolmaly.')
        if not (0 <= easy_percent <= 100):
            errors.append('Ýönekeý soraglaryň bölegi (0-100) arasynda bolmaly.')
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
            flash('Test üstünikli döredilen', 'success')
            return redirect(url_for('tests.index'))
        except sqlite3.IntegrityError:
            db.rollback()
            db.close()
            flash('Ýatda saklamada ýalňyşlyk çykdy: maglumatlary barlaň.', 'danger')

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
        flash('Test tapylmady', 'danger')
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
            errors.append('Testiň adyny giriziň.')
        if total_questions <= 0:
            errors.append('Umumy sorag sany 0-dan uly bolmaly.')
        if not (0 <= easy_percent <= 100):
            errors.append('Ýönekeý soraglaryň göterimi (0-100) arasynda bolmaly.')
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
            flash('Test üstünikli täzelenen', 'success')
            return redirect(url_for('tests.index'))
        except sqlite3.IntegrityError:
            db.rollback()
            db.close()
            flash('Ýatda saklama ýalňyşlygy: maglumatlary barlaň.', 'danger')

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


@tests_bp.route('/save-instance/<int:id>', methods=['POST'])
@login_required
def save_instance(id: int):
    db = get_db_connection()
    test = db.execute('SELECT * FROM tests WHERE id = ?', (id,)).fetchone()
    if not test:
        db.close()
        flash('Test tapylmady', 'danger')
        return redirect(url_for('tests.index'))

    existing = db.execute(
        'SELECT id FROM test_instances WHERE test_id = ? AND parent_instance_id IS NULL',
        (id,),
    ).fetchone()
    if existing:
        db.close()
        flash('Bu test üçin nusga eýýäm bar.', 'warning')
        return redirect(url_for('tests.instances', test_id=id))

    test_subjects = db.execute(
        '''
        SELECT ts.subject_id, ts.question_count, s.answer_count
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

        easy_qs = db.execute(
            '''
            SELECT id, correct_option, subject_id FROM questions
            WHERE subject_id = ? AND difficulty = 'easy' AND is_active = 1
            ORDER BY RANDOM() LIMIT ?
            ''',
            (ts['subject_id'], easy_count),
        ).fetchall()

        hard_qs = db.execute(
            '''
            SELECT id, correct_option, subject_id FROM questions
            WHERE subject_id = ? AND difficulty = 'hard' AND is_active = 1
            ORDER BY RANDOM() LIMIT ?
            ''',
            (ts['subject_id'], hard_count),
        ).fetchall()

        group = [dict(q) for q in list(easy_qs) + list(hard_qs)]
        random.shuffle(group)
        all_questions.extend(group)

    cursor = db.cursor()
    cursor.execute('INSERT INTO test_instances (test_id) VALUES (?)', (id,))
    instance_id = cursor.lastrowid
    for order, q in enumerate(all_questions, 1):
        cursor.execute(
            'INSERT INTO test_instance_questions (instance_id, subject_id, question_id, correct_option, question_order) VALUES (?, ?, ?, ?, ?)',
            (instance_id, q['subject_id'], q['id'], q['correct_option'], order),
        )
    db.commit()
    db.close()

    flash('Test nusgasy ýatda saklanan', 'success')
    return redirect(url_for('tests.instance_detail', instance_id=instance_id))


@tests_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id: int):
    db = get_db_connection()
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('DELETE FROM tests WHERE id = ?', (id,))
    db.commit()
    db.close()
    flash('Test ýok edildi', 'info')
    return redirect(url_for('tests.index'))




@tests_bp.route('/<int:test_id>/instances')
@login_required
def instances(test_id: int):
    db = get_db_connection()
    test = db.execute('SELECT * FROM tests WHERE id = ?', (test_id,)).fetchone()
    if not test:
        db.close()
        flash('Test tapylmady', 'danger')
        return redirect(url_for('tests.index'))

    instances_list = db.execute(
        '''
        SELECT ti.id, ti.created_at, ti.parent_instance_id, COUNT(tiq.id) AS question_count
        FROM test_instances ti
        LEFT JOIN test_instance_questions tiq ON tiq.instance_id = ti.id
        WHERE ti.test_id = ?
        GROUP BY ti.id
        ORDER BY ti.id ASC
        ''',
        (test_id,),
    ).fetchall()
    has_instance = any(i['parent_instance_id'] is None for i in instances_list)
    db.close()
    return render_template('tests/instances.html', test=test, instances=instances_list,
                           has_instance=has_instance)


@tests_bp.route('/instances/<int:instance_id>')
@login_required
def instance_detail(instance_id: int):
    db = get_db_connection()
    instance = db.execute(
        '''
        SELECT ti.id, ti.created_at, ti.test_id, ti.parent_instance_id, t.name AS test_name
        FROM test_instances ti
        JOIN tests t ON t.id = ti.test_id
        WHERE ti.id = ?
        ''',
        (instance_id,),
    ).fetchone()
    if not instance:
        db.close()
        flash('Test nusgasy tapylmady', 'danger')
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

    subjects_map = {}
    for q in questions:
        sid = q['subject_id']
        if sid not in subjects_map:
            subjects_map[sid] = {'name': q['subject_name'], 'questions': []}
        subjects_map[sid]['questions'].append(q)

    is_base = instance['parent_instance_id'] is None
    has_variant = is_base and db.execute(
        'SELECT id FROM test_instances WHERE parent_instance_id = ?', (instance_id,)
    ).fetchone() is not None

    db.close()
    return render_template(
        'tests/instance_detail.html',
        instance=instance,
        subjects=list(subjects_map.values()),
        all_questions=questions,
        is_base=is_base,
        has_variant=has_variant,
    )


@tests_bp.route('/instances/<int:instance_id>/pdf')
@login_required
def export_instance_pdf(instance_id: int):
    db = get_db_connection()
    instance = db.execute(
        '''
        SELECT ti.id, ti.test_id, t.name AS test_name,
               t.total_questions, t.easy_percent
        FROM test_instances ti
        JOIN tests t ON t.id = ti.test_id
        WHERE ti.id = ?
        ''',
        (instance_id,),
    ).fetchone()
    if not instance:
        db.close()
        flash('Test nusgasy tapylmady', 'danger')
        return redirect(url_for('tests.index'))

    rows = db.execute(
        '''
        SELECT tiq.question_order, tiq.question_id,
               s.name AS subject_name, s.answer_count,
               q.question_text, q.question_image
        FROM test_instance_questions tiq
        JOIN subjects s ON s.id = tiq.subject_id
        JOIN questions q ON q.id = tiq.question_id
        WHERE tiq.instance_id = ?
        ORDER BY tiq.question_order ASC
        ''',
        (instance_id,),
    ).fetchall()

    questions_with_options = []
    for row in rows:
        active_keys = ('a', 'b', 'c', 'd', 'e')[:row['answer_count']]
        opts = db.execute(
            'SELECT option_key, option_text, option_image FROM question_options WHERE question_id = ?',
            (row['question_id'],),
        ).fetchall()
        options = {o['option_key']: dict(o) for o in opts}
        for k in ('a', 'b', 'c', 'd', 'e'):
            options.setdefault(k, {'option_key': k, 'option_text': None, 'option_image': None})
        questions_with_options.append((dict(row), options, active_keys, row['subject_name']))

    db.close()

    test_dict = {
        'name': instance['test_name'],
        'total_questions': instance['total_questions'],
        'easy_percent': instance['easy_percent'],
    }
    static_dir = os.path.join(_project_root(), 'static')
    pdf_bytes = _generate_pdf(test_dict, questions_with_options, static_dir)

    safe_name = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in instance['test_name'])
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{safe_name}_nusga{instance_id}.pdf',
    )


@tests_bp.route('/instances/<int:instance_id>/answers-txt')
@login_required
def export_instance_answers_txt(instance_id: int):
    db = get_db_connection()
    instance = db.execute(
        '''
        SELECT ti.id, ti.created_at, t.name AS test_name
        FROM test_instances ti
        JOIN tests t ON t.id = ti.test_id
        WHERE ti.id = ?
        ''',
        (instance_id,),
    ).fetchone()
    if not instance:
        db.close()
        flash('Test nusgasy tapylmady', 'danger')
        return redirect(url_for('tests.index'))

    rows = db.execute(
        '''
        SELECT tiq.question_order, tiq.correct_option,
               s.name AS subject_name
        FROM test_instance_questions tiq
        JOIN subjects s ON s.id = tiq.subject_id
        WHERE tiq.instance_id = ?
        ORDER BY tiq.question_order ASC
        ''',
        (instance_id,),
    ).fetchall()
    db.close()

    answers = []
    for row in rows:
        for k in row['correct_option'].split(','):
            answers.append(k.strip().upper())

    content = ''.join(answers)
    safe_name = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in instance['test_name'])
    return send_file(
        io.BytesIO(content.encode('utf-8')),
        mimetype='text/plain; charset=utf-8',
        as_attachment=True,
        download_name=f'{safe_name}_nusga{instance_id}_jogaplar.txt',
    )


@tests_bp.route('/instances/<int:instance_id>/create-variant', methods=['POST'])
@login_required
def create_variant(instance_id: int):
    db = get_db_connection()
    instance = db.execute(
        'SELECT test_id, parent_instance_id FROM test_instances WHERE id = ?', (instance_id,)
    ).fetchone()
    if not instance:
        db.close()
        flash('Test nusgasy tapylmady', 'danger')
        return redirect(url_for('tests.index'))

    if instance['parent_instance_id'] is not None:
        db.close()
        flash('Görnüşden görnüş döredip bolmaýar.', 'warning')
        return redirect(url_for('tests.instance_detail', instance_id=instance_id))

    existing_variant = db.execute(
        'SELECT id FROM test_instances WHERE parent_instance_id = ?', (instance_id,)
    ).fetchone()
    if existing_variant:
        db.close()
        flash('Bu nusga üçin görnüş eýýäm bar.', 'warning')
        return redirect(url_for('tests.instance_detail', instance_id=instance_id))

    rows = db.execute(
        '''
        SELECT question_id, subject_id, correct_option
        FROM test_instance_questions
        WHERE instance_id = ?
        ORDER BY question_order ASC
        ''',
        (instance_id,),
    ).fetchall()

    questions = [dict(r) for r in rows]
    random.shuffle(questions)

    cursor = db.cursor()
    cursor.execute(
        'INSERT INTO test_instances (test_id, parent_instance_id) VALUES (?, ?)',
        (instance['test_id'], instance_id),
    )
    new_instance_id = cursor.lastrowid
    for order, q in enumerate(questions, 1):
        cursor.execute(
            'INSERT INTO test_instance_questions (instance_id, subject_id, question_id, correct_option, question_order) VALUES (?, ?, ?, ?, ?)',
            (new_instance_id, q['subject_id'], q['question_id'], q['correct_option'], order),
        )
    db.commit()
    db.close()

    flash('Täze görnüş döredilen', 'success')
    return redirect(url_for('tests.instance_detail', instance_id=new_instance_id))


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
        flash('Test nusgasy ýok edilen', 'info')
        return redirect(url_for('tests.instances', test_id=test_id))
    db.close()
    flash('Test nusgasy tapylmady', 'danger')
    return redirect(url_for('tests.index'))
