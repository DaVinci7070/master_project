import hashlib
import os

SECRET_SALT = os.getenv("USER_ID_SECRET_SALT", "default_super_secret_salt_change_me")

def hash_user_id(user_id: str) -> str:
    salted_id = user_id + SECRET_SALT
    return hashlib.sha256(salted_id.encode('utf-8')).hexdigest()