from flask import Blueprint

pos = Blueprint('pos', __name__)

from . import views