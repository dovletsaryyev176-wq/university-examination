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

    app.config['SECRET_KEY'] = 'dev-secret-key-12345'
    
    app.config['DATABASE'] = os.path.join(app.root_path, 'database.db')

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.login_message = "Bu sahypa ýüzlenmek üçin giriň."
    login_manager.login_message_category = "info"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        db = get_db_connection()
        user_data = db.execute('SELECT id, username, full_name FROM users WHERE id = ?', (user_id,)).fetchone()
        db.close()
        
        if user_data:
            return User(user_data['id'], user_data['username'], user_data['full_name'])
        return None

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
        if current_user.is_authenticated:
            return redirect(url_for('users.index'))
        return redirect(url_for('auth.login'))

    return app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)