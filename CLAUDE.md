# CLAUDE.md - Development Guide

## Commands
- Build/Run: `pipenv run python main.py` or `./run.sh`
- Lint: `pipenv run ruff check`
- Install: `pipenv install`
- Dev Install: `pipenv install --dev`

## Code Style
- **Imports**: Group standard library, third-party, and local imports
- **Typing**: Use type hints for function parameters and return values
- **Naming**: Use snake_case for variables/functions, PascalCase for classes
- **Error Handling**: Use try/except with specific exceptions, avoid broad exceptions
- **Async**: Use asyncio for I/O operations, prefer `await` over callbacks
- **Formatting**: Follow PEP 8, max line length 100 characters
- **Documentation**: Add docstrings for classes and non-trivial functions
- **Security**: Never expose API keys, use pyrage for encryption/decryption
- **Logging**: Use the logging module with appropriate levels
- **Media Handling**: Use descriptive labels for media types (photos, videos, files)
- **Encryption**: Always encrypt data before writing to disk; download to memory first

## Project Structure
- Telegram client configuration in main.py
- Data storage/encryption handled in data.py
- Encrypted messages stored in data/messages/
- Session data in data/sessions/
- Media content identified with descriptive labels in message text
- Encrypted media stored in photos subdirectories