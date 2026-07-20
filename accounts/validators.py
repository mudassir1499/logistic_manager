"""
accounts/validators.py

A single source of truth for password strength, lifted out of the old duplicated
checks that lived inline in ``portal/views.py`` (registration + reset). Both the
registration form and the password-reset flow now call ``validate_password_strength``.
"""


def validate_password_strength(password):
    """
    Return an error message string if the password is too weak, else None.

    Rules (unchanged from the original portal implementation):
      - at least 8 characters,
      - at least one uppercase letter,
      - at least one lowercase letter,
      - at least one digit.
    """
    if len(password) < 8:
        return 'Password must be at least 8 characters long.'
    if not any(c.isupper() for c in password):
        return 'Password must contain at least one uppercase letter.'
    if not any(c.islower() for c in password):
        return 'Password must contain at least one lowercase letter.'
    if not any(c.isdigit() for c in password):
        return 'Password must contain at least one digit.'
    return None
