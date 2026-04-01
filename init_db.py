import sqlite3
from werkzeug.security import generate_password_hash

def init_db():
    conn = sqlite3.connect('database.db')
    
    # 1. Читаем структуру из SQL-файла и применяем её
    with open('schema.sql', encoding='utf-8') as f:
        conn.executescript(f.read())
    
    cursor = conn.cursor()

    # 2. Проверяем, есть ли уже админ, чтобы не создавать дубликаты
    cursor.execute("SELECT id FROM users WHERE username = ?", ('admin',))
    if not cursor.fetchone():
        hashed_pw = generate_password_hash('admin123')
        cursor.execute(
            "INSERT INTO users (full_name, username, password) VALUES (?, ?, ?)",
            ('Системный Администратор', 'admin', hashed_pw)
        )
        conn.commit()
        print("База обновлена, пользователь 'admin' создан.")
    else:
        print("База уже готова, пользователь 'admin' уже существует.")
    
    conn.close()

if __name__ == '__main__':
    init_db()