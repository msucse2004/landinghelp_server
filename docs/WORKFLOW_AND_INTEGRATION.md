# Workflow, Scheduling, Release Process & Future Integration

Developer notes for the survey → admin review → quote release → payment → ML scheduling → agent availability → customer calendar → AI assistant → reviews flow.

---

## 1. Workflow state machine

### SurveySubmission.Status

| Status | Meaning | Next allowed |
|--------|--------|--------------|
| `DRAFT` | Customer editing survey | → SUBMITTED (on submit) |
| `SUBMITTED` | Admin reviewing | → REVISION_REQUESTED (admin requests changes), or → AWAITING_PAYMENT (when quote sent) |
| `REVISION_REQUESTED` | Customer must resubmit | → SUBMITTED (on resubmit) |
| `AWAITING_PAYMENT` | Quote sent, waiting payment | → AGENT_ASSIGNMENT (on payment) |
| `AGENT_ASSIGNMENT` | Paid; agent/schedule being set | → SERVICE_IN_PROGRESS (when schedule sent or tasks active) |
| `SERVICE_IN_PROGRESS` | Services in progress | (completed count from AgentAppointmentRequest CONFIRMED) |

**Transitions (where they happen):**

- DRAFT → SUBMITTED: `survey/views.py` (submit); notifications: admin + customer (email + in-app).
- SUBMITTED → REVISION_REQUESTED: `config/views.py` (request revision / section updates); event + in-app + email to customer.
- REVISION_REQUESTED → SUBMITTED: `survey/views.py` (resubmit); event RESUBMITTED.
- SUBMITTED → AWAITING_PAYMENT: `settlement/quote_approval.finalize_and_send_quote` (quote release); event QUOTE_SENT.
- AWAITING_PAYMENT → AGENT_ASSIGNMENT: `settlement/quote_checkout` (payment completion); event PAID.
- AGENT_ASSIGNMENT → SERVICE_IN_PROGRESS: `settlement/views.py` (api_quote_checkout post-payment); optional.
- Schedule sent: `config/schedule_admin_views.submission_review_schedule_finalize`; event SCHEDULE_SENT; submission status not changed (can stay AGENT_ASSIGNMENT or SERVICE_IN_PROGRESS).

### SettlementQuote.Status

| Status | Meaning |
|--------|--------|
| `DRAFT` | Admin editing |
| `NEGOTIATING` | In review |
| `FINAL_SENT` | Sent to customer (price visible to customer) |
| `PAID` | Payment completed |

**Rule:** Customer-facing price/total/checkout may only be shown when `status in (FINAL_SENT, PAID)`. Enforced via `settlement.constants.message_may_include_price`, `can_view_price`, and `quote_for_customer`.

### ServiceSchedulePlan.Status

| Status | Meaning |
|--------|--------|
| `DRAFT` | ML or admin draft |
| `REVIEWING` | Admin editing |
| `FINALIZED` | Admin confirmed (before send) |
| `SENT` | Pushed to customer (legacy `UserSettlementPlan.service_schedule` updated) |
| `ACTIVE` | Optional, for “current” plan |

Display: `schedule_utils.get_schedule_for_display()` prefers ACTIVE/SENT plan → `plan_to_legacy_schedule()`; else falls back to `UserSettlementPlan.service_schedule` (backward compatibility).

### AgentAppointmentRequest.status

| Status | Meaning |
|--------|--------|
| `PENDING` | Waiting agent accept |
| `CONFIRMED` | Date/time confirmed |
| `CANCELLED` | Cancelled |

Customer can rate only CONFIRMED appointments; one `AgentRating` per appointment (optional `appointment` FK).

---

## 2. Scheduling engine

**Location:** `settlement/scheduling_engine.py`, `settlement/agent_scoring.py`, `settlement/schedule_utils.py`.

- **Inputs:** Survey answers, requested services (from quote or submission), entry_date, region/state, agent availability windows (`AgentAvailabilityWindow`), preferred_agent_id, service durations.
- **Outputs:** Draft `ServiceSchedulePlan` with `ServiceScheduleItem`s (starts_at, ends_at, assigned_agent, source_score, source_reason).
- **Logic:**
  - `build_scheduling_context()`: builds services_with_meta, entry_date, agent_windows_by_agent, preferred_agent_id, state_code.
  - If agent windows exist: `suggest_placements_with_availability()` (scores agents, picks best, places in first free window; no overlap per agent).
  - Else: `suggest_placements()` (simple day spread).
  - Agent scoring: `agent_scoring.get_agent_scores_for_submission()` (rating, accept_rate, state/service match, availability fit, workload).
- **Pluggable:** Replace or wrap `suggest_placements` / scoring with an external ML/LLM service; keep `build_scheduling_context()` as input adapter.
- **Management command:** `python manage.py generate_schedule_draft <submission_id>`.
- **Admin:** “ML 초안 생성”, “미배정만 재배치”, “Agent 항목만 재배치” call the same engine with different scopes.

---

## 3. PDF / email release process

**Quote release (FINAL_SENT):**

- **Entry:** `settlement.quote_approval.finalize_and_send_quote(quote, actor)` (used from Admin “승인 후 송부” and config review page).
- **Steps:**
  1. Set `quote.status = FINAL_SENT`, `submission.status = AWAITING_PAYMENT`; create `SurveySubmissionEvent` QUOTE_SENT.
  2. Set `quote.sent_at`.
  3. Email: `quote_email.send_quote_release_email_with_attachments()` — customer preferred language + English PDFs, payment link. Failures do not revert FINAL_SENT; log only.
  4. In-app: `notifications.send_quote_release_message()` — shared conversation, summary + payment link.
- **Price rule:** All release email/message builders use `message_may_include_price(quote)`; only FINAL_SENT/PAID include amounts/checkout.

**Schedule send to customer:**

- **Entry:** `config.schedule_admin_views.submission_review_schedule_finalize`.
- **Steps:** Plan status → FINALIZED then SENT; `plan_to_legacy_schedule()` → `UserSettlementPlan.service_schedule`; `notifications.send_schedule_sent_to_customer()` (in-app + email); `SurveySubmissionEvent` SCHEDULE_SENT.

---

## 4. Notifications (no duplicate sends)

- **Survey submitted:** One call site in `survey/views.py` submit; sends admin notification, customer email, customer in-app message, admin in-app message (each once).
- **Quote sent:** Only `finalize_and_send_quote()` sends release email + in-app message (single path from Admin and config review).
- **Payment complete:** `settlement/views.api_quote_checkout` → `send_payment_complete_notifications()` once (customer + admin in-app, customer + admin + agent email).
- **Schedule sent:** `submission_review_schedule_finalize` calls `send_schedule_sent_to_customer()` once.
- **Agent availability request:** `send_availability_request_to_agent()` (in-app + email) from schedule admin “가용 시간 요청”.

---

## 5. Backward compatibility: UserSettlementPlan.service_schedule

- **Reading:** `schedule_utils.get_schedule_for_display(user_or_plan)` — if customer has an ACTIVE/SENT `ServiceSchedulePlan`, its items are converted with `plan_to_legacy_schedule()` and returned; otherwise the existing `UserSettlementPlan.service_schedule` JSON is returned.
- **Writing:** When admin finalizes schedule, `plan_to_legacy_schedule(schedule_plan)` is written into `UserSettlementPlan.service_schedule` so legacy calendar and any code that reads only `service_schedule` still work.
- **New code:** Prefer `get_schedule_for_display()` and paid-service filtering via `get_paid_service_codes_for_user` + `filter_schedule_to_paid_services` for customer calendar.

---

## 6. Future integration points

### Real payment gateway

- **Current:** `settlement/quote_checkout.py` and `settlement/views.api_quote_checkout` perform a “mock” payment (quote → PAID, plan creation/update).
- **Integration:** Replace or wrap the “complete payment” step with a call to your PG (Stripe, etc.): create payment intent, confirm, then run the same post-payment logic (submission status, UserSettlementPlan, send_payment_complete_notifications). Keep `quote_checkout` as the single place that updates quote/submission/plan and sends notifications.

### Real ML model for scheduling

- **Current:** `scheduling_engine.suggest_placements_with_availability()` and `agent_scoring.get_agent_scores_for_submission()` are rule-based.
- **Integration:** In `scheduling_engine`, add a backend parameter (e.g. `backend='ml'`) and call an external API; map the API response to the same placement dict shape (code, label, service_type, starts_at, ends_at, assigned_agent_id, score, reason). Keep `build_scheduling_context()` as the input contract.

### Web-search-backed AI agent

- **Current:** `ai_agent/llm_adapter.py` has a stub adapter; `ai_agent/tools.py` is a placeholder.
- **Integration:** Implement a tool (e.g. `WebSearchTool`) in `tools.py`; from `ai_agent/services.respond()`, when the LLM or a router requests “search”, call the tool and append results to context or system prompt, then call the LLM again. Do not hard-code web search in views.

---

## 7. Critical policy: price visibility

- **Functions:** `settlement.constants.message_may_include_price(quote_or_status)`, `can_view_price(user, quote)`, `quote_for_customer(quote)`.
- **Rule:** Any customer-facing view, API, or email body that can show amounts/total/checkout must use these (or equivalent) so that nothing is shown when `quote.status` is not FINAL_SENT or PAID.
- **Places checked:** `settlement/views.py` (customer quote, checkout), `settlement/quote_email.py`, `settlement/notifications.py`, `settlement/admin.py` (readonly quote display).
