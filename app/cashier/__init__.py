from flask import Blueprint

cashier = Blueprint('cashier', __name__, url_prefix='/cashier')

from . import views
