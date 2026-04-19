import os
from flask import Flask
from flask_login import LoginManager
from database import get_db_connection
from routes.auth import auth_bp, User
from routes.users import users_bp
from flask import redirect, url_for
from flask_login import current_user
from routes.subjects import subjects_bp
from routes.questions import questions_bp
from routes.tests import tests_bp
from routes.classrooms import classrooms_bp
from routes.students import students_bp
from routes.exam import exam_bp



def create_app():
    app = Flask(__name__)

    # --- Конфигурация ---
    # SECRET_KEY нужен для шифрования сессий (куки). 
    # В реальном проекте лучше хранить в переменных окружения.
    app.config['SECRET_KEY'] = 'dev-secret-key-12345'
    
    # Путь к базе данных (SQLite создаст файл в папке instance или корне)
    app.config['DATABASE'] = os.path.join(app.root_path, 'database.db')

    # --- Настройка Flask-Login ---
    login_manager = LoginManager()
    # Указываем, куда перенаправлять пользователя, если он не вошел (название_блюпринта.функция)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = "Пожалуйста, войдите для доступа к этой странице."
    login_manager.login_message_category = "info"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        """Функция, которая "оживляет" пользователя из базы данных по его ID"""
        db = get_db_connection()
        user_data = db.execute('SELECT id, username, full_name FROM users WHERE id = ?', (user_id,)).fetchone()
        db.close()
        
        if user_data:
            # Создаем объект User, который мы определили в routes/auth.py
            return User(user_data['id'], user_data['username'], user_data['full_name'])
        return None

    # --- Регистрация модулей (Blueprints) ---
    # Это позволяет держать роуты в разных файлах
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp, url_prefix='/users')
    app.register_blueprint(subjects_bp, url_prefix='/subjects')
    app.register_blueprint(questions_bp, url_prefix='/questions')
    app.register_blueprint(tests_bp, url_prefix='/tests')
    app.register_blueprint(classrooms_bp, url_prefix='/classrooms')
    app.register_blueprint(students_bp, url_prefix='/students')
    app.register_blueprint(exam_bp, url_prefix='/exam')


    @app.route('/')
    def index():
        # Если пользователь уже вошел — отправляем в список юзеров
        if current_user.is_authenticated:
            return redirect(url_for('users.index'))
        # Если нет — на страницу логина
        return redirect(url_for('auth.login'))

    return app

# Создаем экземпляр приложения
app = create_app()

if __name__ == '__main__':
    # host='0.0.0.0' — КРИТИЧНО для работы по локальной сети.
    # Это говорит Windows слушать входящие подключения со всех IP-адресов.
    # port=5000 — стандартный порт.
    # debug=True — автоматически перезагружает сервер при изменении кода.
    app.run(host='0.0.0.0', port=5000, debug=True)