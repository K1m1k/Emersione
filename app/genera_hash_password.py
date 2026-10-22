"""Genera un hash PBKDF2 per configurare un account locale Emersione.

Uso: python -m app.genera_hash_password
La password viene richiesta senza mostrarla sul terminale.
"""
import getpass
from app.sicurezza import crea_hash_password


def main() -> None:
    password = getpass.getpass("Password (minimo 14 caratteri): ")
    conferma = getpass.getpass("Ripeti password: ")
    if password != conferma:
        raise SystemExit("Le password non coincidono.")
    try:
        print(crea_hash_password(password))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
