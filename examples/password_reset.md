# Password Reset — Requirements

This document describes the password reset feature of the web application.
Some requirements below are intentionally incomplete so the analyzer has
something to find.

## Functional requirements

- REQ-1: The user can request a password reset from the login page by entering their email address.
- REQ-2: The system must send a reset link to the registered email address.
- REQ-3: The reset link expires after 30 minutes.
- REQ-4: The new password must be at least 8 characters long and contain one digit.
- REQ-5: The reset page should load fast and be user-friendly.
- REQ-6: After too many failed attempts, the account is locked.
- REQ-7: The new password must be at least 10 characters long.
- REQ-8: If the email address is not registered, the system shows a generic message to avoid revealing which accounts exist.
- REQ-9: The user is able to set a new password.
