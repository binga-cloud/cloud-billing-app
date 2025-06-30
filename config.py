import os


class Config:
    SECRET_KEY = 'your-secret-key'  # Keep your existing key

    # Automatic persistent storage in Azure
    SQLALCHEMY_DATABASE_URI = 'sqlite:////home/site/wwwroot/database.db'

    SQLALCHEMY_TRACK_MODIFICATIONS = False