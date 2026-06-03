from io import BytesIO

import openpyxl
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from database import get_db_connection

students_bp = Blueprint('students', __name__)

_HEADER_KEYS = {
    'number':     ['номер', 'number', '№', 'num', 'код', 'id'],
    'last_name':  ['фамилия', 'lastname', 'last_name', 'surname'],
    'first_name': ['имя', 'firstname', 'first_name'],
    'patronymic': ['отчество', 'patronymic', 'middlename', 'middle_name', 'отч'],
    'region':     ['область', 'регион', 'region', 'province'],
}


def _detect_col(headers: list, field: str):
    keywords = _HEADER_KEYS.get(field, [])
    for i, h in enumerate(headers):
        h_lower = str(h).strip().lower() if h else ''
        if any(kw in h_lower for kw in keywords):
            return i
    return None


def _parse_excel(file_bytes: bytes):
    try:
        wb = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as e:
        return None, f'Faýly açmak başartmady: {e}'

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return None, 'Faýl boş'

    first_row = [str(c).strip() if c is not None else '' for c in rows[0]]

    col = {k: _detect_col(first_row, k) for k in _HEADER_KEYS}

    if col['last_name'] is None and col['first_name'] is None:
        col = {'number': 0, 'last_name': 1, 'first_name': 2, 'patronymic': 3, 'region': 4}
        data_rows = rows
    else:
        data_rows = rows[1:]

    missing = [k for k in ('last_name', 'region') if col.get(k) is None]
    if missing:
        return None, (
            f'Hökmany sütünler tapylmady: {", ".join(missing)}. '
            'Birinji setirde «Familýa» we «Welaýat» sütün atlarynyň bardygyny barlaň.'
        )

    def _cell(row, key):
        idx = col.get(key)
        if idx is None or idx >= len(row):
            return ''
        v = row[idx]
        return str(v).strip() if v is not None else ''

    students = []
    for row in data_rows:
        if not any(c for c in row if c is not None and str(c).strip()):
            continue
        last_name = _cell(row, 'last_name')
        if not last_name:
            continue
        students.append({
            'number':     _cell(row, 'number'),
            'last_name':  last_name,
            'first_name': _cell(row, 'first_name'),
            'patronymic': _cell(row, 'patronymic'),
            'region':     _cell(row, 'region') or 'Näbelli',
        })

    if not students:
        return None, 'Maglumat tapylmady'

    return students, None


@students_bp.route('/')
@login_required
def index():
    db = get_db_connection()
    students = db.execute(
        'SELECT * FROM students ORDER BY region, last_name'
    ).fetchall()
    region_stats = db.execute(
        'SELECT region, COUNT(*) AS cnt FROM students GROUP BY region ORDER BY cnt DESC'
    ).fetchall()
    db.close()
    return render_template('students/list.html', students=students, region_stats=region_stats)


@students_bp.route('/import', methods=['POST'])
@login_required
def import_excel():
    file = request.files.get('file')
    if not file or file.filename == '':
        flash('Faýl saýlaň', 'danger')
        return redirect(url_for('students.index'))

    if not file.filename.lower().endswith(('.xlsx', '.xls')):
        flash('Diňe .xlsx we .xls faýllar goldanylýar', 'danger')
        return redirect(url_for('students.index'))

    students, error = _parse_excel(file.read())
    if error:
        flash(f'Import ýalňyşlygy: {error}', 'danger')
        return redirect(url_for('students.index'))

    db = get_db_connection()
    db.execute('DELETE FROM students')
    for s in students:
        db.execute(
            'INSERT INTO students (number, last_name, first_name, patronymic, region) VALUES (?, ?, ?, ?, ?)',
            (s['number'], s['last_name'], s['first_name'], s['patronymic'], s['region']),
        )
    db.commit()
    db.close()

    flash(f'{len(students)} dalaşgär import edildi', 'success')
    return redirect(url_for('students.index'))


@students_bp.route('/clear', methods=['POST'])
@login_required
def clear():
    db = get_db_connection()
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('DELETE FROM exam_sessions')
    db.execute('DELETE FROM students')
    db.commit()
    db.close()
    flash('Dalaşgärleriň sanawy we ähli ýerleşmeler arassalandy', 'info')
    return redirect(url_for('students.index'))
