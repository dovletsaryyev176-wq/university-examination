CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_active INTEGER DEFAULT 1
);

-- Вопросы (CRUD без удаления; только блокировка/разблокировка via is_active)
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    question_text TEXT,
    question_image TEXT,
    correct_option TEXT NOT NULL CHECK (correct_option IN ('a', 'b', 'c', 'd', 'e')),
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