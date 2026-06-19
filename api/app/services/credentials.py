from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class CredentialConfigError(RuntimeError):
    pass


class InvalidCredentialError(ValueError):
    pass


class CredentialCipher:
    def __init__(self, master_key: str):
        if not master_key:
            raise CredentialConfigError(
                "INSTITUTION_CREDENTIALS_MASTER_KEY must be configured"
            )
        derived_key = base64.urlsafe_b64encode(
            hashlib.sha256(master_key.encode("utf-8")).digest()
        )
        self._fernet = Fernet(derived_key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise InvalidCredentialError("Unable to decrypt stored credential") from exc


def get_credential_cipher() -> CredentialCipher:
    return CredentialCipher(settings.INSTITUTION_CREDENTIALS_MASTER_KEY)
