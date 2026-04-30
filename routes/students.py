from io import BytesIO

import openpyxl
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from database import get_db_connection

students_bp = Blueprint('students', __name__)

# Keywords for flexible header detection
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
        return None, f'Не удалось открыть файл: {e}'

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return None, 'Файл пуст'

    first_row = [str(c).strip() if c is not None else '' for c in rows[0]]

    col = {k: _detect_col(first_row, k) for k in _HEADER_KEYS}

    # If key columns not found by header, assume fixed order (no header row):
    # col A=number, B=last_name, C=first_name, D=patronymic, E=region
    if col['last_name'] is None and col['first_name'] is None:
        col = {'number': 0, 'last_name': 1, 'first_name': 2, 'patronymic': 3, 'region': 4}
        data_rows = rows
    else:
        data_rows = rows[1:]

    missing = [k for k in ('last_name', 'region') if col.get(k) is None]
    if missing:
        return None, (
            f'Не найдены обязательные колонки: {", ".join(missing)}. '
            'Убедитесь что в первой строке есть заголовки «Фамилия» и «Область».'
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
            'region':     _cell(row, 'region') or 'Неизвестно',
        })

    if not students:
        return None, 'Не найдено ни одной строки с данными'

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
        flash('Выберите файл', 'danger')
        return redirect(url_for('students.index'))

    if not file.filename.lower().endswith(('.xlsx', '.xls')):
        flash('Поддерживаются только файлы .xlsx и .xls', 'danger')
        return redirect(url_for('students.index'))

    students, error = _parse_excel(file.read())
    if error:
        flash(f'Ошибка импорта: {error}', 'danger')
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

    flash(f'Импортировано {len(students)} студентов', 'success')
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
    flash('Список студентов и все размещения очищены', 'info')
    return redirect(url_for('students.index'))
