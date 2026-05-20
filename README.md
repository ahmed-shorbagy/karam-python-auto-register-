# Karama Registration Automation

Concurrent Playwright-based automation for the Karama ASP.NET WebForms registration portal, with file-based state management and real-time Telegram notifications.

## Prerequisites

- Python 3.10+
- Chromium browser (installed automatically by Playwright)

## Installation

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Configuration

Edit `register.ini`:

| Key                | Description                              | Example               |
|--------------------|------------------------------------------|-----------------------|
| `TELEGRAM_BOT`     | Telegram Bot API token                  | `123456:ABCdefGhI…`  |
| `TELEGRAM_CHANNEL`  | Target chat/channel ID                 | `-1001234567890`      |
| `SLEEP`             | Seconds between folder scans           | `3`                   |
| `CASES_FOLDER`      | Folder to watch for `.txt` case files  | `cases`               |
| `FINISHED_FOLDER`   | Destination for processed files        | `finished`            |
| `THREADS_COUNT`     | Max concurrent browser contexts        | `4`                   |

## Case File Format

Each `.txt` file uses XML-like tags. See `sample_case.txt` for a full example:

```xml
<ssn>28501011234567</ssn>
<firstName>محمد</firstName>
<secondName>أحمد</secondName>
<thirdName>علي</thirdName>
<fourthName>حسن</fourthName>
<city>القاهرة</city>
<address>شارع التحرير</address>
<phoneNumber>01012345678</phoneNumber>
<governorate>
  <option checked="1" value="1">القاهرة</option>
</governorate>
<MaritalStatus>
  <option checked="1" value="2">متزوج</option>
</MaritalStatus>
<Job>موظف</Job>
<ddl>
  <option checked="1" value="3">أمراض مزمنة</option>
</ddl>
<note>ملاحظة</note>
```

## Usage

```bash
python main.py
```

The script will:

1. Read configuration from `register.ini`
2. Continuously monitor `cases/` for new `.txt` files
3. Parse each file and check against `register.json` for duplicates
4. Launch up to `THREADS_COUNT` concurrent Playwright browser contexts
5. Fill and submit the ASP.NET form at the target URL
6. On success: record the SSN in `register.json`, move the file to `finished/`, and send a Telegram notification
7. Log all activity to both stdout and `automation.log`

## State & Idempotency

`register.json` tracks every successfully processed SSN with its request ID, source filename, and timestamp. If the script restarts, already-processed SSNs are skipped automatically.

## Telegram Notifications

Successful submissions trigger an Arabic-formatted message with retry logic for HTTP 429 rate limits. The message includes: timestamp, full name, SSN, phone, request type, a link to view the case, and any notes.
