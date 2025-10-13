from flask import Blueprint

superuser = Blueprint('superuser', __name__, url_prefix='/superuser')

from app.superuser import views
