import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend


def decrypt_session_id(password: str, encrypted_session_id: str, encoded_salt: str) -> str:
    """
    Decrypts a session ID using a password and a salt.

    Args:
        password: The password to use for decryption.
        encrypted_session_id: The base64 encoded encrypted session ID.
        encoded_salt: The base64 encoded salt used for key derivation.

    Returns:
        The decrypted session ID as a string.
    """

    encrypted_session_id_data = base64.b64decode(encrypted_session_id)
    decoded_salt_data = base64.b64decode(encoded_salt)
    key = compute_key_from_password(password, decoded_salt_data)
    session_id_data = decrypt_ecb(key, encrypted_session_id_data)
    session_id = session_id_data.decode("utf-8").strip()
    return session_id


def encrypt_password(user_password: str, web_service_password: str, salt: str) -> str:
    """
    Encrypts a user password using a web service password and a salt.

    Args:
        user_password: The user's password to encrypt.
        web_service_password: The web service password used for key derivation.
        salt: The salt used for key derivation.

    Returns:
        The base64 encoded encrypted user password.
    """

    salt_as_bytes = salt.encode("ascii")
    encryption_key = compute_key_from_password(web_service_password, salt_as_bytes)
    plain_data_as_bytes = user_password.encode("ascii")

    cipher_data_as_string = encrypt_ecb(encryption_key, plain_data_as_bytes)
    return cipher_data_as_string


def compute_key_from_password(password: str, salt_data: bytes) -> bytes:
    """
    Computes a key from a password and a salt using PBKDF2.

    Args:
        password: The password to use for key derivation.
        salt_data: The salt data used for key derivation.

    Returns:
        The derived key as a byte array.
    """

    password_data = password.encode("utf-8")
    key = get_encryption_key_from_password(password_data, salt_data)
    return key


def get_encryption_key_from_password(password: bytes, salt: bytes) -> bytes:
    """
    Derives a key from a password and a salt using PBKDF2.

    Args:
        password: The password to use for key derivation.
        salt: The salt data used for key derivation.

    Returns:
        The derived key as a byte array.
    """

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=32,
        salt=salt,
        iterations=1000,  # Adjust iterations for desired security
        backend=default_backend(),
    )
    key = kdf.derive(password)
    return key


def encrypt_ecb(key: bytes, src: bytes) -> str:
    """
    Encrypts data using AES-256 in Electronic CodeBook (ECB) mode.

    Args:
        key: The encryption key.
        src: The data to encrypt.

    Returns:
        The base64 encoded encrypted data.
    """

    cipher = Cipher(algorithms.AES(key), modes.ECB(), default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(src) + encryptor.finalize()
    return base64.b64encode(ciphertext).decode("utf-8")


def decrypt_ecb(key: bytes, data: bytes) -> bytes:
    """
    Decrypts data using AES-256 in Electronic CodeBook (ECB) mode.

    Args:
        key: The decryption key.
        data: The base64 encoded encrypted data.

    Returns:
        The decrypted data as a byte array.
    """

    cipher = Cipher(algorithms.AES(key), modes.ECB(), default_backend())
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(data) + decryptor.finalize()
    return plaintext
