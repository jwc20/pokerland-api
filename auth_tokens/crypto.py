import binascii
from os import urandom as generate_bytes

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.hashes import SHA512


def create_token_string():
    # django-rest-knox 에서 AUTH_TOKEN_CHARACTER_LENGTH 기본값으로 지정되어 있던 64 사용
    return binascii.hexlify(generate_bytes(int(64 / 2))).decode()


def hash_token(token):
    """
    Calculates the hash of a token.
    input is unhexlified

    token must contain an even number of hex digits or a binascii.Error
    exception will be raised
    """
    digest = hashes.Hash(
        SHA512(),
        backend=default_backend(),
    )
    digest.update(binascii.unhexlify(token))
    return binascii.hexlify(digest.finalize()).decode()
