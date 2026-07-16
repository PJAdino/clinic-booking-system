# Clinic Booking System

A REST API for a small clinic (5 doctors, 30-minute appointment slots) built with Django REST Framework, deployed on GCP Cloud Run with a Supabase Postgres database.

**Live URL:** https://clinic-booking-3141474794.europe-west1.run.app
**Repository:** https://github.com/PJAdino/clinic-booking-system

---

## 1. System Design

### Models
- **Doctor** — `full_name`, `working_start`, `working_end` (working hours treated as clinic-local time, EAT / Africa-Nairobi)
- **Appointment** — `doctor` (FK), `patient_id`, `slot_time` (stored in UTC), `status` (`free` / `booked` / `cancelled` — a three-state field chosen over a boolean, since cancel/reschedule logic needs to distinguish "never booked" from "was booked, now cancelled"), `cancellation_reason`

### Slot representation & concurrency safety
Slots are pre-generated per doctor per 30-minute window within working hours, rather than computed purely on the fly. A **database-level unique constraint** on `(doctor, slot_time)` — scoped to rows where `status="booked"` — guarantees no two appointments can ever exist for the same doctor at the same time, even under concurrent requests. The constraint is conditional (not applied to free/cancelled rows) so a cancelled slot can be rebooked without being blocked by its own old row.

Validation (working hours, not-in-past) is checked first, failing fast for requests that could never succeed regardless of timing. The actual database write then happens inside a transaction; if the unique constraint is violated by a concurrent request, the resulting `IntegrityError` is caught and converted into a clean `slot_taken` error rather than crashing.

### Timezone handling
All timestamps are stored in UTC. Doctor working hours are treated as clinic-local (EAT). Before validating a booking against working hours, the incoming UTC `slot_time` is converted to EAT for comparison. Storage remains single-format (UTC) at all times — conversions happen only at comparison/display boundaries, never as a second stored value.

### Reschedule atomicity
Rescheduling is implemented as a single database transaction: the original slot is freed and the new slot is claimed within the same unit of work (`transaction.atomic()`, with `select_for_update()` locking the original row). If claiming the new slot fails — because it was booked concurrently, triggering the unique constraint — the entire transaction rolls back and the original appointment remains intact. A patient can never end up holding zero slots mid-operation.

### Authentication
Not implemented in this submission due to time constraints. Documented as a known limitation: production use would require verifying requester identity (e.g. JWT) against `patient_id`, plus role-based checks for doctor-initiated actions (e.g. a doctor cancelling their own day). This was a deliberate, time-boxed scope decision, not an oversight.

### Tech stack
**Django REST Framework** — chosen for existing team familiarity, and because Django's ORM provides transaction management (`transaction.atomic()`, `select_for_update()`) and model-level constraints that map directly onto the concurrency decisions above.

### Error handling design
`services.py` (business logic layer) is HTTP-agnostic — it raises a `BookingError` carrying a short internal `code` string (e.g. `"slot_taken"`, `"past_slot"`). `views.py` owns a single `ERROR_STATUS_MAP` dictionary that translates each code into the correct HTTP status. This keeps the service layer reusable outside an HTTP/DRF context and testable without simulating HTTP requests.

| Error code | HTTP status | Rationale |
|---|---|---|
| `not_found` | 404 | Referenced resource doesn't exist |
| `past_slot` | 400 | Invalid regardless of current DB state |
| `outside_working_hours` | 400 | Invalid regardless of current DB state |
| `already_cancelled` | 409 | Conflicts with current state of a specific resource |
| `slot_taken` | 409 | Conflicts with current state of a specific resource |

### Architecture
Business logic lives in `services.py`, separate from `views.py`. Views stay thin — parsing requests and formatting responses only. This keeps validation logic directly testable (no HTTP simulation needed) and reusable across endpoints — reschedule reuses the same slot-validation logic as booking, avoiding duplicated rules.

Four separate `APIView` classes are used instead of one combined class, since a single DRF class can only define one method per HTTP verb — cancel and reschedule both require `PATCH`, so they need distinct classes.

### Trade-off: no serializers.py
With two models and four endpoints, responses are built as plain dictionaries and DRF's `Response()` serializes them directly; incoming fields are validated manually inside `services.py`. This was a deliberate scope decision given project size, not an oversight.

---

## 2. API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Health check — confirms the API is live and responding |
| `POST` | `/appointments/` | Book a slot |
| `GET` | `/doctors/<id>/availability?date=YYYY-MM-DD` | List free slots for a doctor on a date |
| `PATCH` | `/appointments/<id>/cancel` | Cancel an appointment (requires `reason` in body) |
| `PATCH` | `/appointments/<id>/reschedule` | Move an appointment to a new slot (requires `new_slot_time` in body) |

### Trying it out
Visiting the live URL directly in a browser hits the health check and returns:
```json
{"status": "ok", "service": "Clinic Booking API"}
```

Example booking request:
```bash
curl https://clinic-booking-3141474794.europe-west1.run.app/appointments/ \
  -X POST -H "Content-Type: application/json" \
  -d '{"doctor_id": 1, "patient_id": 1, "slot_time": "2026-07-20T10:00:00Z"}'
```
Since no doctors exist yet in the production database, this correctly returns:
```json
{"error": "Doctor not found."}
```
— confirming the full request path (routing → view → service → database) is working end-to-end, even without seed data.

---

## 3. Testing

9 tests, all passing, covering all four service functions:

- **Booking:** happy path, double-booking (concurrency conflict), outside working hours, past slot
- **Cancel:** happy path, cancelling an already-cancelled appointment
- **Reschedule:** happy path, rescheduling to an already-taken slot (verifies atomic rollback — original appointment remains untouched on failure)
- **Availability:** confirms booked slots are correctly excluded from results

Run locally with:
```bash
python manage.py test bookings
```

### Bugs caught by testing

**1. Timezone-naive vs. timezone-aware comparison bug (`get_availability`)**
Initially, `get_availability()` failed to exclude booked slots from results. Root cause: `possible_times` was built with timezone-naive datetimes (`datetime.combine(date, doctor.working_start)`), while `booked_times` from the database were timezone-aware (UTC). The `not in` comparison silently failed to match them, so booked slots leaked through as "free." Fixed by tagging both `datetime.combine()` calls with the clinic timezone (`CLINIC_TZ`).

**2. Import name collision (`timezone`)**
`tests.py` imported `timezone` from Python's built-in `datetime` module alongside using Django's `timezone.now()` — a naming collision where the wrong `timezone` object was resolved, causing `AttributeError: type object 'datetime.timezone' has no attribute 'now'`. Fixed by importing Django's timezone utility under an explicit alias: `from django.utils import timezone as django_timezone`.

### Testing infrastructure note
Tests are designed to run independent of production infrastructure. When run against the real Supabase Postgres instance (rather than local SQLite), Django's test-database create/drop cycle conflicts with Supabase's Session Pooler (`OperationalError: database "test_postgres" is being accessed by other users`), requiring the `--keepdb` flag. This is a deliberate reflection of a broader principle: the test suite should not depend on live infrastructure quirks to run correctly.

---

## 4. Running Locally

```bash
git clone https://github.com/PJAdino/clinic-booking-system.git
cd clinic-booking-system
pip install -r requirements.txt
```

Create a `.env` file in the project root:
```
DATABASE_URL=<your Postgres connection string>
DEBUG=True
```

```bash
python manage.py migrate
python manage.py test bookings
python manage.py runserver
```

---

## 5. Deployment & CI/CD

### Infrastructure
- **Database:** Supabase Postgres (Session Pooler connection), chosen over GCP Cloud SQL for a more generous, ongoing free tier and simpler setup given project scope.
- **Hosting:** GCP Cloud Run, deployed via source-based build (Cloud Build + Buildpacks/Dockerfile).
- **Container:** Single-stage `Dockerfile` (`python:3.12-slim` base) — multi-stage builds were considered but rejected, since all dependencies are pure-Python or precompiled (`psycopg2-binary`), with no build-time toolchain to strip out. Dependency installation is ordered before code copying to take advantage of Docker layer caching.
- **Production server:** `gunicorn`, not Django's `runserver` (which is explicitly unsuitable for production traffic).
- **Secrets:** `DATABASE_URL`, `DEBUG`, and `ALLOWED_HOSTS` are injected as environment variables at deploy time (via Cloud Run config / GitHub Actions secrets) — never hardcoded or committed to the repository.

### CI/CD Pipeline (GitHub Actions)
Configured in `.github/workflows/deploy.yml`.

- **On every pull request / push to `main`:** installs dependencies and runs the full test suite (`python manage.py test bookings --keepdb`). A failing test blocks the pipeline.
- **On push to `main` (i.e. after a PR merge):** automatically deploys to Cloud Run via `gcloud run deploy --source .`, using a dedicated GCP service account authenticated through a GitHub Actions secret (`GCP_SA_KEY`).

### Notable deployment issues encountered and resolved
- **Dockerfile casing:** the file was saved locally as `dockerfile` (lowercase). Windows filesystems are case-insensitive, so local builds worked fine, but Cloud Build (Linux) is case-sensitive and requires the exact filename `Dockerfile`. This silently caused Cloud Run to fall back to auto-detected buildpacks instead of the custom Dockerfile, which then failed with a missing-entrypoint error. Fixed by renaming the file with correct casing.
- **Service account key exposure:** a GCP service account key was briefly committed to git before `.gitignore` was updated to exclude it. GitHub's push protection correctly blocked the push. The exposed key was invalidated and a fresh key generated before proceeding — treated as a real security event, not just a technical blocker.
- **GCP organization policy (`iam.disableServiceAccountKeyCreation`):** blocked service account key creation/listing even for the project Owner. Diagnosed via `gcloud resource-manager org-policies describe`. Resolved by regenerating the service account and key after confirming the policy state; a more robust long-term fix would be Workload Identity Federation (no static key required), which was not implemented given time constraints.
- **Test database conflict in CI:** Supabase's connection pooler conflicted with Django's test-database create/drop cycle in the CI environment (same root cause as the local testing note above). Resolved with `--keepdb`.

---

## 6. AI Reflection

**1. What did you use AI for across the four sections?**
Design reasoning (challenged and refined through structured back-and-forth rather than generated outright), debugging real errors during local and CI/CD setup, explaining unfamiliar concepts — particularly the GCP deployment stack (IAM, service accounts, Cloud Run, Artifact Registry), coming from prior AWS experience rather than GCP — and diagnosing infrastructure failures under time pressure.

**2. Give one example where an AI suggestion improved your work.**
The conditional unique constraint (`UniqueConstraint(..., condition=models.Q(status="booked"))`) — an unconditional constraint would have permanently blocked rebooking a cancelled slot, since the old cancelled row would still violate uniqueness. Scoping it to only `booked` rows was suggested and reasoned through together, and directly reflects the concurrency-safety design the assessment is built around.

**3. Give one example where AI output was wrong or incomplete and how you caught it.**
Deployment hit a real cascading failure that's more instructive than a simple bug fix: a GCP service account key was accidentally committed to git before `.gitignore` excluded it, GitHub's push protection correctly blocked the push, and the recommended fix (delete and regenerate the key) ran into a GCP organization policy (`iam.disableServiceAccountKeyCreation`) that silently blocked key creation, listing, and deletion — even for the project Owner. The first diagnosis assumed a simple permissions gap; only after checking the account's actual IAM roles (confirmed `roles/owner`) and then explicitly querying the org policy itself did the real cause surface. This was caught by verifying each assumption against actual command output rather than accepting the first plausible explanation, and it meant treating a security incident (the exposed key) as a security incident — rotating the credential — rather than just working around the immediate error.

**4. Name two decisions you made without AI. Why did you trust your own judgment there?**
- Keeping the service layer (`services.py`) completely HTTP-agnostic and separate from `views.py`, after reasoning through what "views just handle requests, services hold the logic" actually buys: validation logic becomes testable without simulating HTTP requests at all, and reusable across endpoints — reschedule needs the exact same slot-validation as booking, and duplicating that logic inside two different views would have meant maintaining the same rules in two places.
- Deciding that error codes should be decoupled from HTTP status entirely — `services.py` raises a plain string code (`"slot_taken"`, `"past_slot"`), and a single `ERROR_STATUS_MAP` dictionary in `views.py` is the only place that knows about actual HTTP status numbers. The reasoning: an HTTP status code is meaningless outside an HTTP context, so baking it into the service layer would have undermined the same HTTP-agnostic reusability the layering was meant to protect in the first place.

---


## 7. Known Limitations / Future Work
- No authentication (documented above)
- Doctor-cancels-a-day bulk cancellation not implemented
- `GET /patients/{id}/appointments` and the 1-hour booking lockout bonus endpoints not implemented, given time constraints
