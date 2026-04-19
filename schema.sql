CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT,
    last_name TEXT NOT NULL,
    first_name TEXT NOT NULL,
    patronymic TEXT,
    region TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exam_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS exam_placements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    classroom_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    seat_number INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES exam_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (classroom_id) REFERENCES classrooms(id),
    FOREIGN KEY (student_id) REFERENCES students(id)
);

CREATE TABLE IF NOT EXISTS classrooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    location TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    answer_count INTEGER NOT NULL DEFAULT 4,
    is_active INTEGER DEFAULT 1
);

-- Вопросы (CRUD без удаления; только блокировка/разблокировка via is_active)
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    question_text TEXT,
    question_image TEXT,
    correct_option TEXT NOT NULL,
    difficulty TEXT NOT NULL DEFAULT 'easy' CHECK (difficulty IN ('easy', 'hard')),
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY (subject_id) REFERENCES subjects(id)
);

-- Варианты ответов для вопроса: A/B/C/D/E. У каждого варианта может быть текст и/или картинка.
CREATE TABLE IF NOT EXISTS question_options (
    question_id INTEGER NOT NULL,
    option_key TEXT NOT NULL CHECK (option_key IN ('a', 'b', 'c', 'd', 'e')),
    option_text TEXT,
    option_image TEXT,
    PRIMARY KEY (question_id, option_key),
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    total_questions INTEGER NOT NULL,
    easy_percent INTEGER NOT NULL DEFAULT 50
        CHECK (easy_percent BETWEEN 0 AND 100)
);

CREATE TABLE IF NOT EXISTS test_subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    question_count INTEGER NOT NULL CHECK (question_count > 0),
    UNIQUE (test_id, subject_id),
    FOREIGN KEY (test_id) REFERENCES tests(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES subjects(id)
);

-- Сохранённые экземпляры сгенерированных тестов
CREATE TABLE IF NOT EXISTS test_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (test_id) REFERENCES tests(id) ON DELETE CASCADE
);

-- Конкретные вопросы и правильные ответы для каждого экземпляра теста
CREATE TABLE IF NOT EXISTS test_instance_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    correct_option TEXT NOT NULL,
    question_order INTEGER NOT NULL,
    FOREIGN KEY (instance_id) REFERENCES test_instances(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES subjects(id),
    FOREIGN KEY (question_id) REFERENCES questions(id)
);