# Temp Mail Automation API

This folder contains a small FastAPI service that wraps the deployed temp mail site and exposes a cleaner automation API for:

- creating inboxes
- listing inboxes
- fetching mails
- extracting verification codes
- polling until a verification code arrives

## Quick Start

```bash
cd temp_mail_api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8010
```

## Environment Variables

Create a `.env` file or export these variables before starting:

```bash
TEMP_MAIL_BASE_URL=https://mail.2802644093.com
TEMP_MAIL_DEFAULT_DOMAIN=2802644093.com
TEMP_MAIL_CUSTOM_AUTH=
TEMP_MAIL_LANG=zh
TEMP_MAIL_DB_PATH=./data/inboxes.db
```

`TEMP_MAIL_CUSTOM_AUTH` is only needed if the temp mail site later enables site access passwords.

## Main Endpoints

- `GET /health`
- `POST /api/inboxes`
- `GET /api/inboxes`
- `GET /api/inboxes/{inbox_id}`
- `GET /api/inboxes/{inbox_id}/mails`
- `GET /api/inboxes/{inbox_id}/verification-code`
- `POST /api/inboxes/{inbox_id}/poll-verification-code`
