"""Print fresh secrets for .env:  python -m scripts.gen_keys"""
import secrets

from cryptography.fernet import Fernet

print(f"ENCRYPTION_KEY={Fernet.generate_key().decode()}")
print(f"JWT_SECRET={secrets.token_urlsafe(48)}")
print(f"ADMIN_PANEL_PATH=/panel-{secrets.token_urlsafe(8).lower().replace('_', '').replace('-', '')}")
