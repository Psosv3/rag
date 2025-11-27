import os, base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def b64e(b): return base64.b64encode(b).decode()
def b64d(s): return base64.b64decode(s)

KEY = b64d(os.environ["CHATBOT_KEK_V1_B64"])

def encrypt(plaintext: str) -> str:
    nonce = os.urandom(12)  # number used once
    ct = AESGCM(KEY).encrypt(nonce, plaintext.encode("utf-8"), None)  # AAD=None pour simplifier mais à ajouter company_id & session_id ultérieurmet
    return base64.b64encode(nonce + ct).decode("utf-8")

def decrypt(token_b64: str) -> str:
    raw = base64.b64decode(token_b64)
    nonce, ct = raw[:12], raw[12:]
    pt = AESGCM(KEY).decrypt(nonce, ct, None)
    return pt.decode("utf-8")
