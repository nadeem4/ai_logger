# Privacy

`loglens` sends log data to a third-party AI provider (OpenAI or Anthropic) so it can be
analyzed. This document describes exactly what leaves your machine, when, where it goes,
what the built-in PII scrubbing catches (and does not catch), how to extend it, how to
turn it off for specific loggers, and what governs the data once it reaches a provider.

If you only read one section, read [What scrubbing does *not* catch](#what-scrubbing-does-not-catch).

## What data leaves the machine

`AIHandler` (`loglens/handlers/ai_handler.py`) formats every buffered `logging.LogRecord`
into a dict via `JsonFormatter` (`loglens/utils/json_formatter.py`), runs that dict through
PII scrubbing, then renders the *scrubbed* batch into a plaintext prompt with Jinja2
(`loglens/templates/default_log_prompt.jinja2`) and passes that prompt as the single
message content to the configured provider's chat/completion API.

The formatted (pre-scrub) dict for each record includes:

- `message` — the fully-formatted log message (`record.getMessage()`, i.e. with `%s`-style
  args already substituted in)
- `levelname` / `levelno` — e.g. `"ERROR"` / `40`
- `name` — the logger's name (e.g. `"my_app.payments"`)
- `timestamp`, `pathname`, `filename`, `module`, `lineno`, `funcName`, `thread`,
  `threadName`, `process`, `processName`
- `exception_info` — the formatted traceback, if the record was logged with `exc_info=True`
- `stack_info` — formatted stack info, if the record was logged with `stack_info=True`
- `extras` — a dict of every keyword you passed via `logger.error(..., extra={...})`

**All of the above is scrubbed** (see below), but not all of it is necessarily *sent*: the
default prompt template only renders `timestamp`, `levelname`, `name`, `message`,
`pathname`/`lineno`/`funcName`, `exception_info`, `stack_info`, and `extras` (as JSON) into
the outgoing text. `levelno`, `filename`, `module`, `thread`/`threadName`, and
`process`/`processName` are computed and scrubbed but not included in the default prompt —
though a custom template (`LOGLENS_JINJA_TEMPLATE_DIR`) could add them.

**When:** a batch is sent when it reaches `LOGLENS_BATCH_SIZE` records, or every
`LOGLENS_FLUSH_INTERVAL_SECONDS` (whichever comes first), or on handler shutdown
(`close()` / interpreter exit via `logging.shutdown()`).

**Where:** to whichever provider `LOGLENS_PROVIDER` selects (`openai` or `anthropic`),
using that provider's official SDK with its default endpoint. There is currently no
self-hosted or on-device option (see [When to avoid sending anything](#when-to-avoid-sending-anything-at-all)).

## What scrubbing catches

PII scrubbing runs on every string value in the formatted record dict (recursively, through
nested dicts/lists in `extras`) before the prompt is built. It is **on by default**
(`LOGLENS_PII_USE_DEFAULT_RULES=true`) and applies these rules
(`loglens/utils/pii_filter.py`, `DEFAULT_PII_RULES`):

| Rule | Pattern (informal) | Example input | Example output |
|---|---|---|---|
| `email` | `local-part@domain.tld` | `contact bob@example.com` | `contact [REDACTED_EMAIL]` |
| `ipv4` | four dot-separated 1–3 digit groups | `client 10.0.0.5 connected` | `client [REDACTED_IP] connected` |
| `credit_card_visa` | 13 or 16 digits starting with `4` | `card 4111111111111111` | `card [REDACTED_CREDIT_CARD]` |
| `credit_card_mastercard` | 16 digits starting with `51`–`55` | `card 5500000000000004` | `card [REDACTED_CREDIT_CARD]` |
| `credit_card_amex` | 15 digits starting with `34`/`37` | `card 340000000000009` | `card [REDACTED_CREDIT_CARD]` |

These are plain regexes with no checksum (Luhn) validation and no context-awareness — a
13–16 digit number that happens to match one of the card patterns is redacted whether or
not it is actually a card number, and vice versa.

## What scrubbing does *not* catch

The default rule set is a short, fixed list. Anything not in that list is sent to the
provider **unmodified**. In particular, it does **not** catch:

- **Person names.** `logger.error("Escalated to Jane Doe for review")` — `"Jane Doe"` is
  sent as-is; there is no name-detection rule.
- **Postal addresses.** `logger.info("Shipping to 221B Baker Street, London NW1 6XE")` —
  the address is sent as-is.
- **Secrets embedded in free text.** `logger.debug(f"Retrying with key {api_key}")` or a
  stack trace that happens to contain a password, bearer token, or connection string — none
  of these match the default rules, so they pass through verbatim. There is no
  generic-secret-pattern rule (no entropy-based or keyword-based detection).
- **Card numbers outside Visa/Mastercard/Amex.** Discover (`6011...`), Diners Club, JCB,
  and other card brands have no matching rule and are sent unredacted.
- **Phone numbers, national ID / SSN-style numbers, IPv6 addresses.** None of these have a
  default rule either (the source even flags this: *"Add more rules as needed (e.g., phone
  numbers, SSNs — be careful with SSN regex accuracy)"*).

Treat the default rules as a minimum floor, not a compliance control. If your logs might
contain any of the above, add custom rules (below), scrub upstream before the message
reaches `AIHandler`, or don't attach `AIHandler` to that logger at all.

## How to add custom rules

Custom rules are applied *in addition to* the default rules (unless you disable the
defaults with `LOGLENS_PII_USE_DEFAULT_RULES=false`). The simplest path is the
`LOGLENS_PII_RULES_JSON` environment variable, which `Settings` parses as a JSON array of
rule objects:

```jsonc
[
  {
    "name": "string — a label for the rule (used only for readability)",
    "regex": "string — a Python re pattern, compiled with re.compile()",
    "replacement": "string — passed to Pattern.sub(); may use backreferences like \\1"
  },
  ...
]
```

Worked example — redacting an internal employee-ID format like `EMP-12345`:

```bash
export LOGLENS_PII_RULES_JSON='[{"name": "employee_id", "regex": "EMP-\\d{5}", "replacement": "[REDACTED_EMPLOYEE_ID]"}]'
```

With that set, `logger.warning("Escalated by EMP-40231")` becomes `"Escalated by
[REDACTED_EMPLOYEE_ID]"` in the scrubbed record before it's ever rendered into a prompt.

Because `LOGLENS_PII_RULES_JSON` is parsed as `list[dict[str, str]]`, every field must be a
plain string — you cannot pass a pre-compiled `re.Pattern` or a callable replacement through
the environment variable. If you construct `AIHandler` in code rather than purely through
environment configuration, you can pass richer rules (a compiled `Pattern`, or a callable
replacement function) directly:

```python
from loglens import AIHandler
from loglens.utils.pii_filter import scrub_pii_from_dict

custom_rules = [{"name": "employee_id", "regex": r"EMP-\d{5}", "replacement": "[REDACTED_EMPLOYEE_ID]"}]

handler = AIHandler(
    pii_scrubber=lambda data: scrub_pii_from_dict(data, custom_rules=custom_rules),
)
```

## How to disable sending entirely, per logger

`loglens` is opt-in: a logger only reaches `AIHandler` if a handler chain leads to it, so
the most direct way to exclude a logger is to **never attach `AIHandler` (or a
`QueueHandler` that feeds one) to it** in the first place.

If a logger is picking up an `AIHandler` it inherits from an ancestor logger (Python's
`logging` module propagates records up the logger hierarchy by default), you have two
options without restructuring your handler setup:

1. **Stop propagation for that logger:**

   ```python
   import logging

   logging.getLogger("my_app.payments.raw_card_dumps").propagate = False
   ```

   Records logged to that logger (and its children) will never reach the ancestor's
   `AIHandler`, or any other ancestor handler.

2. **Filter by logger name on the handler itself:**

   ```python
   import logging

   class ExcludeLoggerFilter(logging.Filter):
       def __init__(self, excluded_prefix: str) -> None:
           super().__init__()
           self.excluded_prefix = excluded_prefix

       def filter(self, record: logging.LogRecord) -> bool:
           return not record.name.startswith(self.excluded_prefix)

   ai_handler.addFilter(ExcludeLoggerFilter("my_app.payments.raw_card_dumps"))
   ```

   This keeps the shared `AIHandler` instance in place for everything else while excluding
   one subtree of loggers.

## When to avoid sending anything at all

If no log from your application should ever leave the machine, don't attach `AIHandler`
anywhere, or scope its use to a dedicated, clearly-named logger that only receives
messages you have already reviewed. The `local` extra (`pip install loglens[local]`,
`transformers` + `torch`) is declared in `pyproject.toml` for on-device analysis, but at
the time of writing it adds no on-device provider implementation — there is no
`LLMProvider` in `loglens/providers/` that runs a local model. Installing `[local]` alone
does not currently keep data on-device; the only providers implemented are `OpenAIProvider`
and `AnthropicProvider`, both of which call an external API.

## Data retention

Once a batch is sent, its retention is governed by the provider's own policies, not by
`loglens` — the package does not control or track what happens to data after
`provider.complete()` returns:

- OpenAI: <https://openai.com/policies/api-data-usage-policies/>
- Anthropic: <https://www.anthropic.com/legal/privacy>

Review the policy for whichever provider you configure via `LOGLENS_PROVIDER` before
sending anything you wouldn't want retained under that provider's terms.
