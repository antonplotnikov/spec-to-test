# Reference specification — account security

Used by tests/test_reference_spec.py to measure analysis quality. Each
requirement's expected findings are listed in that test. Clear requirements
(no expected findings) check for false positives.

## English

- REF-01: The system must send a password reset link to the registered email address within 60 seconds.
- REF-02: If the email address is not registered, the system must display the message "If the account exists, a link has been sent."
- REF-03: The reset link must expire 30 minutes after it is generated.
- REF-04: After 5 consecutive failed login attempts, the account must be locked for 15 minutes.
- REF-05: Passwords must be stored as salted bcrypt hashes.
- REF-06: The system shall encrypt all personal data at rest using AES-256.
- REF-07: The reset page should load quickly and be user-friendly.
- REF-08: The user can change the password.
- REF-09: The password must have a minimum length.
- REF-10: The user enters the new password twice.
- REF-11: The new password must be at least 8 characters long.
- REF-12: The new password must be at least 12 characters long.
- REF-13: Admins must be able to export the audit log.
- REF-14: Admins must not export the audit log.

## Українська

- REF-15: Система повинна надіслати лист підтвердження протягом 5 хвилин.
- REF-16: Інтерфейс має бути зручним.
- REF-17: Користувач може завантажити аватар.

## Русский

- REF-18: Система должна заблокировать учетную запись после 3 неудачных попыток входа.
- REF-19: Количество попыток ограничено.
- REF-20: Пользователь вводит email в форму.
