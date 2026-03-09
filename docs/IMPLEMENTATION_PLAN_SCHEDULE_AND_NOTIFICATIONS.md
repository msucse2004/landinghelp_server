# Implementation Plan: Full Survey → Quote → Payment → Schedule → Service Day Flow

**Target scenario (13 steps)** mapped to current codebase and gaps. No code changes in this document; analysis and phased plan only.

---

## 1. Reusable Existing Pieces

| Area | What Exists | Location / Notes |
|------|-------------|------------------|
| **Survey → Admin review** | SurveySubmission (DRAFT → SUBMITTED), SurveySubmissionEvent, SurveySubmissionSectionRequest; admin review list/detail | `survey/models.py`, `config/views.py` (submission_review_list, submission_review) |
| **Revision request** | REVISION_REQUESTED status, section-level requests, customer message + email | `config/views.py` (submission_review_request_revision, submission_review_request_section_updates), `settlement/notifications.py` (send_revision_requested_customer_message) |
| **Quote lifecycle** | SettlementQuote (DRAFT → NEGOTIATING → FINAL_SENT → PAID), auto draft from submission, admin price edit, approve & send | `settlement/models.py`, `settlement/quote_draft.py`, `settlement/quote_approval.py`, `config/views.py` (submission_review_update_quote_prices, submission_review_approve_quote) |
| **Quote → Customer** | finalize_and_send_quote: status, submission status, QUOTE_SENT event, send_quote_to_customer (email), send_quote_sent_customer_message (inbox) | `settlement/quote_approval.py`, `settlement/quote_email.py`, `settlement/notifications.py` |
| **Price visibility** | can_view_price, message_may_include_price; customer_quote shows pay button only when FINAL_SENT | `settlement/constants.py`, `templates/services/customer_quote.html` |
| **Payment (mock)** | api_quote_checkout: PAID, UserSettlementPlan create/update, ensure_plan_service_tasks, subscription tier upgrade, send_payment_complete_notifications (customer + agent email) | `settlement/views.py` (_process_quote_checkout, api_quote_checkout), `settlement/post_payment.py` |
| **Post-payment schedule** | build_initial_schedule_from_quote (entry_date or today+7, single-date or week), ensure_plan_service_tasks from quote.items | `settlement/post_payment.py` |
| **Plan & tasks** | UserSettlementPlan.service_schedule (JSON), PlanServiceTask per quote item, link to AgentAppointmentRequest | `settlement/models.py`, Admin inline |
| **Admin scheduling view** | submission_review shows required_tasks, pending/confirmed counts, assigned_agent | `config/views.py` (submission_review), `templates/app/submission_review.html` |
| **Customer calendar** | Dashboard + settlement_quote: plan_schedule_json, enrich_schedule_with_appointment_status, drag-and-drop, agent selection | `config/views.py` (customer_dashboard, plan calendar), `settlement/views.py` (settlement_quote), `templates/app/customer_dashboard.html` |
| **Agent appointment** | AgentAppointmentRequest (PENDING/CONFIRMED/CANCELLED), preferred_time, confirmed_time_slot, confirmed_at; Conversation per appointment; agent calendar view | `settlement/models.py`, `messaging/signals.py`, `config/views.py` (agent_appointment_calendar), `settlement/views.py` (api_confirm_appointment etc.) |
| **Agent selection** | get_agents_for_survey_fragment (state + service_codes), Agent list in survey + plan; preferred_agent_id in answers; UserSettlementPlan.assigned_agent | `settlement/views.py`, `survey/views.py`, `templates/survey/_agent_selection_fragment.html` |
| **Agent rating (display)** | AgentRating (rater, agent, score, comment), get_agent_rating_summary; shown in agent list and admin | `accounts/models.py`, `settlement/views.py` (agent list payload) |
| **Messaging** | Conversation (APPOINTMENT / NOTICE), survey_submission-linked shared thread (customer + admin), Message, MessageRead, MessageTranslation | `messaging/models.py`, `settlement/notifications.py` (_get_or_create_shared_conversation) |
| **Translations / i18n** | get_display_text, preferred_language, quote_email body in one language | `translations`, `settlement/quote_email.py` |
| **LLM usage** | api_service_suggest (service codes from query), _schedule_via_llm (schedule draft from entry_date + services) | `settlement/views.py` |

---

## 2. Missing Backend Pieces

| # | Missing Piece | Notes |
|---|----------------|------|
| 1 | **Quote PDF generation** | No PDF of quote; needed for “quote PDFs in 2 languages” (customer preferred + English). |
| 2 | **Dual-language in email/message** | Current email is single language (customer preferred). Need: attach or link PDF in preferred + English; optional second PDF or single PDF with two sections. |
| 3 | **Payment link in email and in-app message** | send_quote_to_customer and send_quote_sent_customer_message do not include a URL to customer_quote or checkout. Need stable URL (e.g. `/services/settlement/my-quote/` or tokenized link). |
| 4 | **Admin notification on payment complete** | send_payment_complete_notifications notifies customer and assigned agent only; no explicit “payment received” to admin (e.g. message or email). |
| 5 | **ML-based schedule draft** | build_initial_schedule_from_quote is rule-based (SCHEDULE_PRIORITY + single date). No ML model or LLM call for “optimal” date allocation from survey constraints. _schedule_via_llm exists for a different flow (settlement_quote). |
| 6 | **Agent availability (when2meet-style)** | No model or API for agents to submit available time slots (e.g. date + time ranges). AgentAppointmentRequest has preferred_time (free text) and confirmed_time_slot; no structured availability slots. |
| 7 | **Optimization: agent availability + survey → draft schedule** | No service that takes (submission/quote constraints + agent availability) and produces a draft schedule (e.g. assign agent slots to service dates). |
| 8 | **“Final schedule” sent to customer** | No explicit step “admin confirms schedule → send to customer”. Customer already sees plan.service_schedule; no “final schedule” event or notification. |
| 9 | **Service-day detail panel (data)** | No API or view that returns “today’s services” for the logged-in customer (filter plan + appointments by date) for a dedicated panel. |
| 10 | **AI agent (admin info + web search + LLM)** | No backend that combines admin-managed content, web search, and LLM to answer customer questions (e.g. chat or Q&A endpoint). |
| 11 | **Customer review/rating after in-person service** | AgentRating exists but no flow for customer to submit rating after CONFIRMED appointment (no API, no “rate this agent” from conversation or dashboard). |
| 12 | **Agent selection influenced by rating** | Agent list is filtered by state + service_codes and ordered; rating is displayed but not explicitly used for ranking. |

---

## 3. Missing Frontend Pieces

| # | Missing Piece | Notes |
|---|----------------|------|
| 1 | **Payment link in email/message UI** | Email and in-app message body do not show a “Pay now” or “View quote & pay” link; customer must go to app and navigate. |
| 2 | **Quote PDF download** | No customer-facing “Download quote (PDF)” in preferred and English (or single PDF with both). |
| 3 | **Admin: adjust draft schedule in calendar UI** | submission_review shows required_tasks and scheduling summary but no calendar grid to move/reschedule tasks by date (admin side). Admin can only use Django Admin or customer’s plan; no dedicated “admin schedule editor” for that submission. |
| 4 | **Agent: when2meet-style availability input** | No UI for agent to mark available dates/times (e.g. calendar or list of slots). |
| 5 | **Admin: “Send final schedule” action** | No button or flow to “lock” or “send final schedule” to customer with a notification. |
| 6 | **Customer: “Today’s services” / service-day panel** | Dashboard shows calendar and pending appointments but no focused “today” panel with service details (what, when, where, agent contact, etc.). |
| 7 | **AI agent chat / Q&A** | No chat or Q&A UI that calls backend (admin content + web search + LLM). |
| 8 | **Customer: submit rating after appointment** | No form or modal “Rate this agent” after CONFIRMED in-person service (e.g. from dashboard or conversation). |

---

## 4. Proposed Model Changes

| Model | Change | Purpose |
|-------|--------|--------|
| **New: QuotePdfAttachment or QuoteDocument** | Optional: store generated PDF paths or keys (e.g. `quote_id`, `language_code`, `file`) for “quote in 2 languages” and attachment/link in email. | Audit, idempotent attach, multi-language PDF. |
| **New: AgentAvailabilitySlot** | agent (FK), date (date), time_start, time_end (or slot_type); optional recurrence. | When2meet-style availability. |
| **AgentAppointmentRequest** | Optional: availability_slot (FK to AgentAvailabilitySlot, nullable). | Link appointment to a chosen slot. |
| **UserSettlementPlan or SurveySubmission** | Optional: final_schedule_sent_at (DateTimeField, null). | Track “final schedule sent to customer”. |
| **SurveySubmissionEvent.EventType** | Add e.g. `FINAL_SCHEDULE_SENT`. | Audit trail. |
| **Message or Conversation** | No schema change; optional: store “payment link” or “quote PDF link” in body or as structured meta (if needed). | Can use existing body + URL. |
| **AgentRating** | Optional: appointment (FK to AgentAppointmentRequest, null). | Link rating to specific appointment. |

**Migration summary (high level)**

- Add `AgentAvailabilitySlot` (agent, date, time_start, time_end, created_at, etc.).
- Add `AgentAppointmentRequest.availability_slot_id` (nullable FK).
- Add `UserSettlementPlan.final_schedule_sent_at` or `SurveySubmission.final_schedule_sent_at` (nullable).
- Add `SurveySubmissionEvent` event type `FINAL_SCHEDULE_SENT`.
- Optional: `QuotePdfAttachment` (quote, language_code, file or storage key); or store paths in settings/cache only.
- Optional: `AgentRating.appointment_id` (nullable FK).

---

## 5. Proposed API/View Changes

| Area | Change | Purpose |
|------|--------|--------|
| **Quote send flow** | After finalize_and_send_quote: (1) Generate quote PDF(s) (preferred + en), (2) Attach or link in email, (3) Include payment link in email body and in send_quote_sent_customer_message body. | Target 4–5. |
| **Payment link** | Single canonical URL for “my quote & pay” (e.g. `settings.SITE_URL + reverse('customer_quote')`); optionally tokenized link for email. | Target 5. |
| **Notifications** | send_payment_complete_notifications: add admin notification (email and/or in-app message to staff). | Target 6. |
| **Schedule draft (post-payment)** | New service: e.g. `build_ml_schedule_draft(submission, quote)` → returns schedule dict; call from post_payment or from admin “Regenerate draft” (reuse/adapt _schedule_via_llm or new ML). | Target 7. |
| **Admin schedule editor** | New view: e.g. `submission_schedule_editor(request, submission_id)` + API to update `UserSettlementPlan.service_schedule` (and optionally create/update AgentAppointmentRequest placeholders). | Target 7. |
| **Agent availability** | New APIs: e.g. `GET/POST /api/agent/availability/` (list/submit slots); `GET /api/agent/availability/?agent_id=&from=&to=`. | Target 8. |
| **Optimization** | New service: `compute_optimal_draft_schedule(plan, quote, agent_availability)` → merge survey constraints + agent slots into one draft (e.g. assign agent to dates). | Target 9. |
| **Final schedule** | New action: “Send final schedule to customer” (set final_schedule_sent_at, create event, send message + optional email with calendar summary). | Target 10. |
| **Customer calendar** | Existing dashboard/plan calendar; optionally filter or highlight by “purchased service type” if needed (already driven by plan.service_schedule). | Target 10. |
| **Service-day panel** | New API: e.g. `GET /api/me/today-services/?date=YYYY-MM-DD` returning services and appointments for that date. New fragment or section in dashboard for “Today’s services”. | Target 11. |
| **AI agent** | New API: e.g. `POST /api/chat/` or `POST /api/support/ask` (question + context); backend combines admin content, web search (e.g. Serper/SerpAPI or similar), LLM. | Target 12. |
| **Customer rating** | New API: e.g. `POST /api/appointments/<id>/rate/` (score, comment); create AgentRating, optionally restrict to CONFIRMED and same customer. | Target 13. |
| **Agent list ordering** | When returning agents for survey/plan, order by rating (and/or accept_rate) in addition to state/service filter. | Target 13. |

---

## 6. Proposed Background Jobs / Async Tasks

| Job | Trigger | Action |
|-----|---------|--------|
| **Quote PDF generation** | On “Approve & send” or cron before send | Generate PDF (preferred + en), store or attach; if async, finalize_and_send_quote may enqueue and send email when ready. |
| **Payment received (admin)** | On api_quote_checkout success | Already in request; add admin notification (sync or enqueue). |
| **Schedule draft (ML)** | After PAID or on admin “Regenerate draft” | Call build_ml_schedule_draft; update plan.service_schedule; optional: notify admin. |
| **Reminders** | Existing (e.g. survey reminder, appointment reminder) | No change for this plan. |
| **Optional: Final schedule digest** | When admin clicks “Send final schedule” | Send email/message to customer with summary (can be sync). |

Prefer Celery or Django-Q if already in use; otherwise sync in view is acceptable for MVP, with PDF generation and “send final schedule” as first candidates for async if needed.

---

## 7. Implementation Order

**Phase 1 – Quote send & payment link (targets 4, 5, 6)**  
1. Add payment link (URL) to quote email and to send_quote_sent_customer_message body.  
2. Optional: Add quote PDF generation (one or two languages) and attach or link in email/message.  
3. Add admin notification on payment complete (in-app message and/or email).

**Phase 2 – Schedule draft & admin calendar (targets 7, 10)**  
4. Introduce ML/LLM-based schedule draft from quote + submission (e.g. extend post_payment or new module).  
5. Admin schedule editor view + API to edit plan.service_schedule (and optionally tasks/appointments).  
6. “Final schedule sent” state (field + event) and “Send final schedule” action with customer notification.

**Phase 3 – Agent availability & optimization (targets 8, 9)**  
7. Model + API for agent availability slots.  
8. Agent UI to submit availability (when2meet-style).  
9. Service to merge agent availability + survey/quote constraints into draft schedule; hook into admin flow.

**Phase 4 – Service day & AI (targets 11, 12)**  
10. API “today’s services” and customer dashboard “service day” panel.  
11. AI agent endpoint (admin content + web search + LLM) and minimal chat/Q&A UI.

**Phase 5 – Rating & selection (target 13)**  
12. Customer rating API and UI after CONFIRMED appointment; optional AgentRating.appointment_id.  
13. Agent list ordering by rating (and accept_rate) for survey/plan selection.

---

## Migration Checklist (Explicit)

- [ ] `AgentAvailabilitySlot`: migrations for new model (agent, date, time_start, time_end, etc.).  
- [ ] `AgentAppointmentRequest`: add nullable `availability_slot_id` FK.  
- [ ] `UserSettlementPlan` or `SurveySubmission`: add `final_schedule_sent_at` (nullable DateTimeField).  
- [ ] `SurveySubmissionEvent.EventType`: add choice `FINAL_SCHEDULE_SENT`.  
- [ ] Optional: `QuotePdfAttachment` (or equivalent) for PDF paths.  
- [ ] Optional: `AgentRating.appointment_id` (nullable FK).  
- [ ] Data migration: none required for existing quotes/appointments; new fields nullable.

---

## Risks and Compatibility

| Risk | Mitigation |
|------|------------|
| **PDF dependency** | Use a single library (e.g. WeasyPrint or reportlab); optional feature flag so “send quote” works without PDF. |
| **Email size (attachments)** | Prefer “link to download PDF” over large attachments, or two emails (one per language). |
| **Payment link security** | Use same auth as customer_quote (login required); avoid sensitive tokens in URL; optional signed token with short TTL for “pay this quote” link. |
| **Agent availability schema** | Start with simple (date + time range); avoid overfitting to one when2meet UX so backend can support multiple UIs. |
| **ML schedule quality** | Keep rule-based fallback; run ML draft only when conditions are met; admin always can edit. |
| **Backward compatibility** | New fields nullable; existing submission_review and customer flows unchanged until new actions are used. |
| **Existing submissions** | final_schedule_sent_at null = “not sent”; no migration of old data needed. |
| **AgentRating uniqueness** | Current constraint (rater, agent) one rating per customer–agent; if linking to appointment, consider one rating per appointment (relax or add appointment_id and unique on appointment). |

---

## Summary Table: Target vs Current

| Step | Target | Current | Gap |
|------|--------|--------|-----|
| 1 | Customer submits → admin review | ✅ | — |
| 2 | Admin requests revision | ✅ | — |
| 3 | Admin releases final quote | ✅ | — |
| 4 | App message + email with quote PDFs (2 langs) | Partial (message + email, no PDF, 1 lang) | PDF, second language |
| 5 | Payment link in email/message | ❌ | Add URL to body |
| 6 | Notify customer + admin on payment | Customer + agent ✅; admin ❌ | Admin notify |
| 7 | ML schedule draft, admin adjust in calendar | Rule-based draft ✅; no admin calendar edit | ML draft, admin editor |
| 8 | Agent availability (when2meet) | ❌ | Model + API + UI |
| 9 | Agent availability + survey → optimal draft | ❌ | New service |
| 10 | Send final schedule, calendar by service | Calendar ✅; no “final sent” step | final_schedule_sent_at + action |
| 11 | Service day: detail panel | ❌ | API + panel |
| 12 | AI agent (admin + web + LLM) | LLM for service suggest only | New endpoint + UI |
| 13 | Customer rating after service; affects selection | Model + display ✅; no submit flow; not used in sort | Submit API + UI; ordering |
