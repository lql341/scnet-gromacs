# WorkBuddy first-use interaction

This reference is for a WorkBuddy client. It assumes the host exposes the
native `AskUserQuestion` tool (aliases have been seen as `ask_user_question`
and `ask_followup_question`). The tool renders a small question card with a
header, one question and 2–4 options; `multiSelect` is supported.

A Markdown instruction alone is not sufficient: the host must expose the tool,
and the agent must call it. This skill therefore also ships a deterministic
helper that turns the current `doctor.py` state into the next question payload.

## Why a helper

`doctor.py` already reports the blocking category. The helper removes the
agent's guesswork:

```text
status JSON -> workbuddy_first_use.py -> AskUserQuestion payload
```

The helper never reads credentials, never renders UI and never submits a job.

## Flow

1. Run the read-only doctor and keep the JSON outside the repository:

   ```bash
   mkdir -p .private
   python3 scripts/doctor.py --json > .private/workbuddy-doctor.json
   ```

2. Ask the next question:

   ```bash
   python3 scripts/workbuddy_first_use.py \
     --status .private/workbuddy-doctor.json
   ```

   For a returning user who has already confirmed account activation:

   ```bash
   python3 scripts/workbuddy_first_use.py \
     --status .private/workbuddy-doctor.json \
     --account-confirmed
   ```

3. Pass the returned `question` object to WorkBuddy's `AskUserQuestion` tool.
   The output is shaped like:

   ```json
   {
     "next": "credentials",
     "tool": "AskUserQuestion",
     "question": {
       "header": "凭证",
       "question": "SCNet OpenAPI 凭证准备怎么提供？",
       "multiSelect": false,
       "options": [
         {"label": "已配置，重新检查", "description": "..."},
         {"label": "去终端配置", "description": "..."}
       ]
     }
   }
   ```

4. Apply the answer and repeat from step 1.

## Question states

| `next` | Meaning | Agent action |
| --- | --- | --- |
| `account` | Account activation is not confirmed | Ask; stop if not activated |
| `credentials` | Credentials absent or unknown | Ask; hand off secrets to terminal |
| `region` | Region missing | Ask; rerun doctor with `--region` |
| `queue` | CPU/DCU queue missing | Ask; rerun doctor with queues |
| `configuration` | Profile incomplete | Ask; fix profile or pass values |
| `online` | Local checks pass | Ask whether to run `--online` |
| `ready` | Online read-only check passed | Report verified |
| `blocked` | Online check failed | Show error and retry/later |

## Credentials

Never put AK/SK, private keys or credential-file contents into:

- the `AskUserQuestion` header/question;
- option labels or descriptions;
- chat text;
- the repository.

When the user selects “去终端配置”, show the command returned in
`terminal_command`, for example:

```bash
python3 "<scnet-hpc>/scripts/scnet.py" setup new --mode openapi
```

Pause until the user has run it in a visible terminal, then re-run doctor.
Use the shared `scnet-hpc-openapi` credential store or the three
`SCNET_OPENAPI_*` environment variables.

## Online verification

Run online only after the user has answered the account/credential/configuration
questions:

```bash
python3 scripts/doctor.py \
  --profile clusters/<profile>.conf \
  --online \
  --cluster <hpc-profile> \
  --json > .private/workbuddy-doctor.json

python3 scripts/workbuddy_first_use.py \
  --status .private/workbuddy-doctor.json \
  --account-confirmed \
  --online
```

Only `next=ready` with `readiness.remote=verified` may be reported as verified.
A failed card must remain `blocked`, not “ready with a warning”.

## Fallback

If `AskUserQuestion` is unavailable in the host version:

- ask the same questions as plain text in chat;
- still do not request secrets;
- still require one category at a time;
- still re-run doctor after each answer;
- do not pretend a local web page is the WorkBuddy native panel.

If WorkBuddy later exposes a different question schema, adapt the helper's
`question` object; keep the state machine and secret boundary unchanged.

## What this does not do

- It does not create a second credential store.
- It does not render a browser GUI.
- It does not submit a job.
- It does not prove account activation or device availability.
