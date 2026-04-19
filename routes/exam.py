import heapq
import io
import os
from collections import defaultdict

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required

from database import get_db_connection

exam_bp = Blueprint('exam', __name__)


def _project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _find_font(bold=False):
    candidates = (
        [
            r'C:\Windows\Fonts\arialbd.ttf',
            '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
            '/Library/Fonts/Arial Bold.ttf',
            '/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf',
        ] if bold else [
            r'C:\Windows\Fonts\arial.ttf',
            '/System/Library/Fonts/Supplemental/Arial.ttf',
            '/Library/Fonts/Arial.ttf',
            '/usr/share/fonts/truetype/msttcorefonts/Arial.ttf',
        ]
    )
    return next((p for p in candidates if os.path.exists(p)), None)


# ─── Algorithm ────────────────────────────────────────────────────────────────

def _arrange_no_adjacent(students: list) -> list:
    """
    Greedy max-heap: always place the most frequent remaining region
    that differs from the previous seat. Minimises same-region adjacency.
    When one region dominates (> 50 % of seats) some conflicts are unavoidable.
    """
    if not students:
        return []

    buckets: dict[str, list] = defaultdict(list)
    for s in students:
        buckets[s['region']].append(s)

    # (-count, region_name) — region_name used as stable tiebreaker
    heap = [(-len(lst), region) for region, lst in buckets.items()]
    heapq.heapify(heap)

    result: list = []

    while heap:
        neg, region = heapq.heappop(heap)

        if result and result[-1]['region'] == region and heap:
            # Same as previous — swap with next most frequent
            neg2, region2 = heapq.heappop(heap)
            result.append(buckets[region2].pop())
            if buckets[region2]:
                heapq.heappush(heap, (-len(buckets[region2]), region2))
            heapq.heappush(heap, (neg, region))
        else:
            result.append(buckets[region].pop())
            if buckets[region]:
                heapq.heappush(heap, (-len(buckets[region]), region))

    return result


def _count_conflicts(students: list) -> int:
    return sum(
        1 for i in range(len(students) - 1)
        if students[i]['region'] == students[i + 1]['region']
    )


# ─── PDF ──────────────────────────────────────────────────────────────────────

def _generate_pdf(session_name: str, classrooms_data: list) -> bytes:
    """classrooms_data: [{'classroom': {...}, 'students': [...]}]"""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    font_name = 'Helvetica'
    reg = _find_font(bold=False)
    bold = _find_font(bold=True)
    if reg and bold:
        try:
            pdf.add_font('Arial', '', reg)
            pdf.add_font('Arial', 'B', bold)
            font_name = 'Arial'
        except Exception:
            pass

    for room_data in classrooms_data:
        c = room_data['classroom']
        sts = room_data['students']
        conflicts = _count_conflicts(sts)

        pdf.add_page()

        # Header
        pdf.set_font(font_name, 'B', 16)
        pdf.cell(0, 10, text=session_name, align='C', new_x='LMARGIN', new_y='NEXT')

        pdf.set_font(font_name, 'B', 13)
        pdf.cell(0, 8, text=c['name'], align='C', new_x='LMARGIN', new_y='NEXT')

        pdf.set_font(font_name, '', 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(
            0, 6,
            text=(f"Место: {c['location']}   |   "
                  f"Вместимость: {c['capacity']}   |   "
                  f"Размещено: {len(sts)}"),
            align='C', new_x='LMARGIN', new_y='NEXT',
        )
        pdf.set_text_color(0, 0, 0)
        pdf.ln(5)

        # Table header
        COL_W = [12, 20, 95, 60]
        HDRS  = ['№', 'Номер', 'ФИО', 'Область']
        pdf.set_font(font_name, 'B', 10)
        pdf.set_fill_color(60, 120, 200)
        pdf.set_text_color(255, 255, 255)
        for w, h in zip(COL_W, HDRS):
            pdf.cell(w, 8, text=h, border=1, fill=True, align='C')
        pdf.ln()
        pdf.set_text_color(0, 0, 0)

        pdf.set_font(font_name, '', 9)
        prev_region = None
        for i, s in enumerate(sts, 1):
            conflict = prev_region is not None and s['region'] == prev_region
            if conflict:
                pdf.set_fill_color(255, 200, 120)
            elif i % 2 == 0:
                pdf.set_fill_color(240, 245, 255)
            else:
                pdf.set_fill_color(255, 255, 255)

            first    = (s.get('first_name') or '')[:1]
            patronym = (s.get('patronymic') or '')[:1]
            initials = (first + '.' if first else '') + (patronym + '.' if patronym else '')
            full_name = f"{s['last_name']} {initials}".strip()

            row_vals = [str(i), str(s.get('number') or ''), full_name, s.get('region') or '']
            for w, val in zip(COL_W, row_vals):
                pdf.cell(w, 7, text=val, border=1, fill=True,
                         align='C' if w <= 20 else 'L')
            pdf.ln()
            prev_region = s['region']

        pdf.ln(2)
        pdf.set_font(font_name, '', 8)
        if conflicts:
            pdf.set_text_color(180, 80, 0)
            pdf.multi_cell(
                0, 5,
                text=f'* Оранжевым выделены {conflicts} случай(-ев) смежного размещения студентов из одной области.',
            )
        else:
            pdf.set_text_color(0, 140, 0)
            pdf.cell(0, 5, text='✓ Все студенты из разных областей — конфликтов нет.')
        pdf.set_text_color(0, 0, 0)

    return bytes(pdf.output())


# ─── Routes ───────────────────────────────────────────────────────────────────

@exam_bp.route('/')
@login_required
def index():
    db = get_db_connection()
    sessions = db.execute(
        '''
        SELECT es.id, es.name, es.created_at,
               COUNT(DISTINCT ep.classroom_id) AS classroom_count,
               COUNT(ep.id) AS student_count
        FROM exam_sessions es
        LEFT JOIN exam_placements ep ON ep.session_id = es.id
        GROUP BY es.id
        ORDER BY es.id DESC
        '''
    ).fetchall()
    db.close()
    return render_template('exam/list.html', sessions=sessions)


@exam_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    db = get_db_connection()
    classrooms = db.execute(
        'SELECT * FROM classrooms WHERE is_active = 1 ORDER BY capacity DESC'
    ).fetchall()
    total_students = db.execute('SELECT COUNT(*) FROM students').fetchone()[0]

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        classroom_ids = request.form.getlist('classroom_ids', type=int)

        errors = []
        if not name:
            errors.append('Введите название размещения.')
        if not classroom_ids:
            errors.append('Выберите хотя бы один класс.')
        if total_students == 0:
            errors.append('Нет студентов. Сначала импортируйте список.')

        selected_rooms = []
        if not errors:
            ph = ','.join('?' * len(classroom_ids))
            selected_rooms = db.execute(
                f'SELECT * FROM classrooms WHERE id IN ({ph}) ORDER BY capacity DESC',
                classroom_ids,
            ).fetchall()
            total_capacity = sum(c['capacity'] for c in selected_rooms)
            if total_capacity < total_students:
                errors.append(
                    f'Недостаточно мест: выбранная вместимость {total_capacity}, '
                    f'а студентов {total_students}. Добавьте ещё классы.'
                )

        if errors:
            for e in errors:
                flash(e, 'danger')
            db.close()
            return render_template(
                'exam/create.html',
                classrooms=classrooms,
                total_students=total_students,
                selected_ids=classroom_ids,
                form_name=name,
            )

        # Load students and arrange
        students = [dict(s) for s in db.execute('SELECT * FROM students').fetchall()]
        arranged = _arrange_no_adjacent(students)

        # Assign to classrooms sequentially
        placements = []
        idx = 0
        for room in selected_rooms:
            cap = min(room['capacity'], len(arranged) - idx)
            if cap <= 0:
                break
            for seat, student in enumerate(arranged[idx:idx + cap], 1):
                placements.append((room['id'], student['id'], seat))
            idx += cap

        cursor = db.cursor()
        cursor.execute('INSERT INTO exam_sessions (name) VALUES (?)', (name,))
        session_id = cursor.lastrowid
        for classroom_id, student_id, seat_number in placements:
            cursor.execute(
                'INSERT INTO exam_placements (session_id, classroom_id, student_id, seat_number) VALUES (?, ?, ?, ?)',
                (session_id, classroom_id, student_id, seat_number),
            )
        db.commit()
        db.close()

        flash(f'Размещение «{name}» создано — {len(placements)} студентов распределено', 'success')
        return redirect(url_for('exam.detail', id=session_id))

    db.close()
    return render_template(
        'exam/create.html',
        classrooms=classrooms,
        total_students=total_students,
        selected_ids=[],
        form_name='',
    )


def _load_classrooms_data(db, session_id: int) -> list:
    rows = db.execute(
        '''
        SELECT ep.seat_number, ep.classroom_id,
               c.name AS classroom_name, c.location, c.capacity,
               s.id AS student_id, s.number AS student_number,
               s.last_name, s.first_name, s.patronymic, s.region
        FROM exam_placements ep
        JOIN classrooms c ON c.id = ep.classroom_id
        JOIN students s ON s.id = ep.student_id
        WHERE ep.session_id = ?
        ORDER BY c.name, ep.seat_number
        ''',
        (session_id,),
    ).fetchall()

    classrooms_map: dict = {}
    for row in rows:
        cid = row['classroom_id']
        if cid not in classrooms_map:
            classrooms_map[cid] = {
                'classroom': {
                    'id': cid,
                    'name': row['classroom_name'],
                    'location': row['location'],
                    'capacity': row['capacity'],
                },
                'students': [],
            }
        classrooms_map[cid]['students'].append(dict(row))

    result = list(classrooms_map.values())
    for rd in result:
        rd['conflicts'] = _count_conflicts(rd['students'])
    return result


@exam_bp.route('/<int:id>')
@login_required
def detail(id: int):
    db = get_db_connection()
    session = db.execute('SELECT * FROM exam_sessions WHERE id = ?', (id,)).fetchone()
    if not session:
        db.close()
        flash('Размещение не найдено', 'danger')
        return redirect(url_for('exam.index'))

    classrooms_data = _load_classrooms_data(db, id)
    db.close()

    total_conflicts = sum(rd['conflicts'] for rd in classrooms_data)
    return render_template(
        'exam/detail.html',
        session=session,
        classrooms_data=classrooms_data,
        total_conflicts=total_conflicts,
    )


@exam_bp.route('/<int:id>/pdf')
@login_required
def export_pdf(id: int):
    db = get_db_connection()
    session = db.execute('SELECT * FROM exam_sessions WHERE id = ?', (id,)).fetchone()
    if not session:
        db.close()
        flash('Размещение не найдено', 'danger')
        return redirect(url_for('exam.index'))

    classrooms_data = _load_classrooms_data(db, id)
    db.close()

    # Rename keys for PDF helper
    for rd in classrooms_data:
        rd['classroom']['name'] = rd['classroom']['name']

    pdf_bytes = _generate_pdf(session['name'], classrooms_data)
    safe = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in session['name'])
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{safe}.pdf',
    )


@exam_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete(id: int):
    db = get_db_connection()
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('DELETE FROM exam_sessions WHERE id = ?', (id,))
    db.commit()
    db.close()
    flash('Размещение удалено', 'info')
    return redirect(url_for('exam.index'))
