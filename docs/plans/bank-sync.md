# Bank sync for Spanish accounts (Santander ES, Revolut)

Status: **plan, not approved.** No production code until the spike passes go/no-go.

**Decided (27 Nov 2026):**
- **Balances:** suggest, one click. The sync fetches the bank-reported balance. The Update panel and Needs attention show it with its date, and you accept it with one click. `current_balance` stays manual-owned and is never auto-written.
- **Overlap:** statement wins. An upload archives `bank_sync` rows in its range; the sync skips dates a statement covers.
- **Email ingest:** keep it until sync is proven for Santander, then remove it (phase 5).
- **Revolut CSV fee bug:** fixed separately, now.

Goal: pull booked transactions (and maybe balances) for Santander ES and Revolut
through a PSD2 aggregator, feeding the existing import pipeline. Replaces the
email route. Principle: **swappable and never load-bearing.** If the sync dies,
statement/CSV upload works exactly as today.

---

## 1. What I verified (27 Nov 2026)

### Enable Banking: coverage (from its public bank list, `enablebanking.com/api/aspsps`, 2,813 entries)

| ASPSP | Country | PSU types | Auth | Max consent | Beta |
|---|---|---|---|---|---|
| `Banco Santander` (BIC BSCHESMMXXX) | ES | personal, business | redirect | 15,552,000 s = **180 days** | no |
| `Revolut` (BIC REVOLT21) | ES | personal, business | redirect | **180 days** | no |

The "Santander details not yet available" note on `docs/markets/es/` refers only to
the *notes* section; the bank itself is listed and not beta. The ES market runs on
**Redsys**, and allows **one active authentication session per user per TPP**.
The LT page says Revolut auth goes through the Revolut app, and Revolut credit-card
accounts only appear in the in-app consent flow. **Unverified until the spike:**
that both banks actually link and return data. Being listed is not proof.

### Restricted production (docs: `docs/api/linked-accounts/`, FAQ, Terms)
- Sign up with an email link, then go to Control Panel → API applications → register an app with environment **Production**. The app starts **Inactive**.
- Click "Activate by linking accounts". This runs the Enable Banking auth page, then the bank's SCA. The app becomes **Active (restricted)**.
- Restricted apps can only read linked accounts. Unlinked accounts are stripped, so an auth can return an empty list.
- The privacy/terms/GDPR-email checks are skipped in restricted mode.
- Terms: production use is limited to linked accounts, for evaluation or personal use by private individuals. "The number of Linked Accounts per Application may be limited." No number is given.
- **Redirect URL:** must be whitelisted at registration. Firefly III's docs say production requires **HTTPS** (sandbox accepts HTTP), and Actual Budget says the same. A plain `http://localhost` callback is therefore out. See §4.4.

### Auth
- Each request carries `Authorization: Bearer <JWT>`.
- The JWT is **RS256** only. Header `kid` = application id. Claims: `iss="enablebanking.com"`, `aud="api.enablebanking.com"`, `iat`, `exp`.
- Max JWT lifetime is **24 h**.
- Keys: generate locally with `openssl genrsa 4096` plus a self-signed cert, or let the Control Panel generate them in the browser.

### Flow and consent
- Flow: `GET /aspsps?country=ES` → `POST /auth` → user goes to `url` → callback with `code` and `state` → `POST /sessions {code}` → `session_id` + accounts.
- `POST /auth` takes `access.valid_until`, `aspsp{name,country}`, `state`, `redirect_url` and `psu_type`.
- `valid_until` can be at most now + `maximum_consent_validity` (180 days here), and **the bank may shorten it**. Actual Budget's docs say "90 days at most", which contradicts this; the spike will show what we actually get.
- Session statuses: `AUTHORIZED | EXPIRED | REVOKED | CANCELLED | CLOSED | INVALID | PENDING_AUTHORIZATION | RETURNED_FROM_BANK`. An early expiry returns `401 EXPIRED_SESSION`, and the fix is a new auth.

### Rate limits
- Enable Banking publishes no quota of its own; the Terms say quotas "may apply".
- Many banks allow **4 unattended fetches per day**. A request counts as "attended" when PSU headers are sent (`Psu-Ip-Address`, `Psu-User-Agent`, …). You must send all of a bank's `required_psu_headers` or none, or you get `422 PSU_HEADER_NOT_PROVIDED`.
- Over the limit you get `429 ASPSP_RATE_LIMIT_EXCEEDED`. Enable Banking advises waiting 6 h.

### Data
- **Transactions:** `GET /accounts/{id}/transactions?date_from&date_to&continuation_key&transaction_status&strategy`. Page until `continuation_key` is null; empty pages can still carry a key.
- **Transaction fields:**
  - `entry_reference` (use this as the id; the FAQ says **not** `transaction_id`, and it may be synthetic)
  - `transaction_amount{amount,currency}`, `credit_debit_indicator` (amounts are unsigned, so the sign comes from CRDT/DBIT)
  - `status` (`BOOK|PDNG|HOLD|CNCL|RJCT|SCHD|OTHR`)
  - `booking_date`, `value_date`, `transaction_date`
  - `remittance_information[]`, `creditor.name`, `debtor.name`, and their accounts
  - `bank_transaction_code{code,sub_code,description}`, `merchant_category_code`
  - `exchange_rate`, `balance_after_transaction`, `note`, `reference_number`
- **History:** full history only in roughly the **first hour after auth**. After that, many banks cap it at **90 days**. The FAQ says most give at least a year in that first window.
- **Balances:** `GET /accounts/{id}/balances` → `[{balance_amount, balance_type, reference_date, last_change_date_time}]`. Common types are `CLBD` (closing booked), `ITAV` (interim available) and `XPCD` (expected).
- **Details:** `GET /accounts/{id}/details` → name, currency, `usage` PRIV/ORGA, `cash_account_type`.

### Free-tier stability (Terms)
- The service is free of charge, and "no fees will be applied retroactively without prior notice".
- It is provided **as is / as available**. Enable Banking may modify or discontinue functionality at any time and can terminate for misuse or AML reasons. No SLA, and no commitment to keep the free tier.
- There is no public pricing page (`/pricing` returns 404). Commercial pricing is volume-based, by contact.

→ It's free today, with nothing that keeps it free. This confirms the
"never load-bearing" principle.

### Other free options for an individual in Spain
- **GoCardless Bank Account Data (ex-Nordigen):** closed to new signups, according to Actual Budget's docs and the openbankingtracker guide. GoCardless's own marketing page has no notice, and the dashboard is login-gated.
- **Yapily, Plaid, TrueLayer, Tink, Salt Edge:** sandbox-only or sales-led for EU production.
- **SimpleFIN:** about $15/yr, but North America only.
- **Akahu:** NZ only.
- **Teller:** US only.
- **open-banking.io:** €3/mo, a one-person service promoted by its own author on dev.to. Not credible as a dependency.
- **Firefly III and Actual Budget** both integrate Enable Banking; Actual also lists GoCardless as closed.
- I could not read the openbankingtracker guide in full; the site returned HTTP 429. Its search summary names Enable Banking as "the closest self-serve replacement in Europe", consistent with the above.

**Conclusion:** Enable Banking is the only realistic free option. No second free
provider exists to fail over to, so the fallback is manual upload.

---

## 2. Spike (throwaway, about half a day, nothing in the repo)

Run everything from a scratch folder **outside the repo**. Payload dumps are real
financial data, so delete them after the go/no-go.

1. **Keys.** Run `openssl genrsa -out eb.key 4096` and `openssl req -new -x509 -key eb.key -out eb.crt -days 1825`. Keep the key outside the repo, with `chmod 600`.
2. **Register.** Sign up at enablebanking.com, then go to Control Panel → new application → **Production** and upload `eb.crt`.
   - Redirect URL: try `https://localhost:8443/bank-sync/callback`. Note whether it's accepted. If it isn't, use any HTTPS URL you control (e.g. a GitHub Pages stub) and note that.
   - Record the app id.
3. **Activate.** Use "Activate by linking accounts" for **Santander ES (personal)** and **Revolut ES (personal)**.
   - Record which accounts each bank exposes: Santander checking/card; Revolut one account per currency pocket or one multi-currency account?
   - Record the SCA steps and the `valid_until` each bank granted.
4. **Script** (about 80 lines, `requests` + `PyJWT[crypto]`). Within the **first hour**:
   - Mint a JWT and check `GET /aspsps?country=ES`.
   - Run `POST /auth` per bank (valid_until = now + 180 days), complete it in the browser, and copy `code` from the landing URL.
   - Call `POST /sessions`.
   - Dump `/details`, `/balances`, and `/transactions` with `strategy=longest` to JSON.
5. **Re-fetch** after more than 1 h and again the next day, unattended (no PSU headers). Check:
   - history depth after the first-hour window;
   - `entry_reference` stability across fetches;
   - PDNG→BOOK transitions (does the reference, date or description change?);
   - whether 3 unattended fetches in a day succeed;
   - one attended fetch with PSU headers set from the local machine (does the bank accept `Psu-Ip-Address: 127.0.0.1`?).
6. **Compare** one full closed month against the existing `.xlsx` statement and the Revolut CSV:
   - row count and signed sum on BOOK rows, which should match exactly;
   - which date field matches the statement's "Transaction date";
   - Revolut fees and FX: is a card payment in USD a separate row, and in which currency;
   - **description quality:** run `normalize_description` + the cascade (no Ollama, read-only, on a DB copy) over `remittance_information` / `creditor.name` and compare the category hit rate with the statement descriptions for the same rows.

### Go/no-go

**GO** (per bank, all must hold):
- it links with a personal PSU;
- consent is ≥ 90 days;
- the booked month matches the statement or CSV exactly (count and sum);
- a stable per-row id exists (`entry_reference`, or a content key that doesn't change across fetches);
- ≥ 2 unattended fetches a day succeed;
- the category hit rate is within about 5 pp of the statement's.

**Partial GO:** only one bank passes. Build it for that bank only. The design is per connection, so nothing changes.

**NO-GO:** neither passes, or descriptions are unusable. Delete the app and keys, and stay on uploads. The cost is half a day.

---

## 3. Phases (if go)

| # | Phase | Contents |
|---|---|---|
| 0 | Prep | Fix the Revolut CSV fee bug (below). Add `ParsedTxn.external_id`. |
| 1 | Provider interface + Enable Banking adapter | `services/bank_sync/` with interface, adapter, JWT, errors. Unit tests on recorded (anonymized) spike payloads. |
| 2 | Connections + link flow | `bank_connections` / `bank_connection_accounts` tables (Alembic). `POST /bank-sync/connections` (start), `POST /bank-sync/callback` (complete), account → app-account mapping. |
| 3 | Sync into the pipeline | `run_bank_sync` → `preview_import`/`commit_import(source="bank_sync")`. Overlap rules. Scheduler following the email pattern. |
| 4 | Surfacing | Update panel: per-connection status, "Sync now", "Reconnect". Two new Needs-attention checks. |
| 4b | Balance suggestion | Store the last `RemoteBalance` per mapped account on `bank_connection_accounts` (amount, currency, as_of, type). Show "Bank says €X as of …, Use this" in the Update panel and on the stale-balance attention item. Accepting it goes through the existing `PUT /accounts/{id}/balance`. Never auto-written. Balance type: prefer `CLBD`, else `ITAV`; the spike confirms which ones each bank returns. Only native-currency remote accounts feed the suggestion. |
| 5 | Retire email ingest | After Santander sync has run cleanly for a few weeks. Delete `email_ingest/`, the Santander email parser, the Gmail config and the endpoint; keep `source="email"` handling for existing rows. |

**Pre-existing bug found while reading (fixed separately):** `RevolutParser`
ignored the `Fee` column. In `input/revolut_espana.csv` the two "Premium plan
fee" rows have `Amount 0.00, Fee 8.99`, so they imported as €0. The signed
amount is now `Amount − Fee`.

---

## 4. Design

### 4.1 Provider interface (`services/bank_sync/provider.py`)

Modelled on `FxProvider`/`PriceProvider`. Everything provider-specific stays in the adapter.

```python
class BankSyncProvider(ABC):
    name: str                                    # "enablebanking"
    def start_link(self, institution: str, country: str, redirect_url: str,
                   state: str, valid_until: datetime) -> LinkStart: ...   # .url
    def complete_link(self, params: Mapping[str, str]) -> LinkResult:
        # → opaque provider_state (JSON), valid_until, list[RemoteAccount]
        ...
    def fetch_transactions(self, provider_state: dict, remote_account: str,
                           date_from: date, date_to: date,
                           psu: PsuContext | None) -> list[ParsedTxn]: ...
    def fetch_balance(self, provider_state: dict, remote_account: str) -> RemoteBalance | None: ...
    def revoke(self, provider_state: dict) -> None: ...
```

- **Neutral errors:** `ConsentExpired`, `RateLimited(retry_after)`, `ProviderUnavailable`, `ProviderConfigError`. The scheduler only knows these.
- **What the rest of the app sees:** `ParsedTxn` (plus the optional `external_id`), `RemoteAccount(remote_id, name, currency, iban_masked)` and `RemoteBalance(amount, currency, as_of)`. No Enable Banking field names leak out.
- **Switching providers:** a new adapter plus one line in a `get_bank_sync_provider()` factory keyed on `BANK_SYNC_PROVIDER`. The `provider_state` JSON blob means the schema never changes per provider.
- **`ParsedTxn.external_id: str | None = None`:** when it's set, `compute_dedup_hash` uses `account|provider|external_id` instead of the content hash. This makes sync idempotent even if a description or date shifts between fetches. Statement and CSV rows are unchanged.

### 4.2 Mapping Enable Banking → `ParsedTxn`
- Import **only `status=BOOK`**. Pending card holds change amount and date, and the email layer exists to handle exactly that kind of churn. Skipping PDNG keeps sync rows final.
- **amount:** `Decimal(transaction_amount.amount)`, negated when `credit_debit_indicator == "DBIT"`. **currency:** `transaction_amount.currency`.
- **date:** `transaction_date or booking_date`. The spike confirms which one matches the statement's "Transaction date". Overlap logic and month buckets depend on this matching.
- **raw_description:** a per-bank composer inside the adapter. The default is `creditor.name` (debits) or `debtor.name` (credits), falling back to `" ".join(remittance_information)`. The spike picks the composition that maximises cascade hits. If Santander's remittance carries the same `COMPRA …, TARJ. :*NNNN` boilerplate, `normalize.py` already strips it. New boilerplate gets added there and nowhere else.
- **txn_type:** from `bank_transaction_code` (ISO 20022 domain/family codes: card → `card_payment`, `RCDT/ICDT` → `transfer`, `CHRG` → `fee`, `DD` → `direct_debit`, …). Fall back to the existing description heuristic (`_infer_type`, moved somewhere both can share). `txn_type` stays informational.
- **Revolut:** one provider account per currency pocket is likely. Mapping is **many remote accounts → one app account**, as today's CSV does with mixed currencies. Exchanges between pockets appear as two rows, which is today's CSV behavior too. Fees: check whether they come as separate rows (the spike settles it).
- **Amounts in `Numeric(18,4)`** via `Decimal(str)`, never float. `fx_rate_to_base` is still captured by `commit_import` through `to_base`. No new FX path.

### 4.3 Sources, dedup and overlap
- `Transaction.source` gains `"bank_sync"`. It's a plain string column, so there's no migration for the value itself.
- **Within sync:** dedup is by `external_id`. Archived rows keep their hash, so a row the user archived is never re-imported.
- **Across sources:** descriptions differ between the API, the `.xlsx` and the CSV, so content hashes won't collide. Dates and amounts can match by accident, so I'd use an explicit precedence rule rather than fuzzy matching:
  - **Statement wins (recommended, Q3).** `commit_import(source="statement")` archives overlapping `bank_sync` rows in its date range, which generalises today's email-supersede rule.
  - The sync never imports rows dated ≤ the account's latest live `statement` row (a per-account watermark). This avoids double counting when you fall back to uploads for a period and then sync again.
- **First sync:** start from the watermark + 1 day (or a `sync_from` per mapped account), not the full 1-year first-hour window. Otherwise it would duplicate history you've already statemented.
- **Email rows:** a bank-sync import also archives overlapping `email` rows, the same as a statement does. That retires the email layer's data cleanly.
- `missing_statements` stays email-only. Months covered by `bank_sync` are complete and shouldn't be flagged.

### 4.4 Secrets and the redirect flow
- **`.env` (server-side only):** `BANK_SYNC_PROVIDER=enablebanking`, `ENABLEBANKING_APP_ID`, `ENABLEBANKING_KEY_PATH` (a PEM outside the repo, `chmod 600`, under `~/.config/home_finance/`), `ENABLEBANKING_REDIRECT_URL`.
- The JWT is minted in the adapter with `PyJWT[crypto]` (new dependency, with `cryptography`), `exp = iat + 1h`, and cached until it's close to expiry. The key is never logged or sent to the frontend.
- `provider_state` (the `session_id`) lives in the DB. It's useless without the private key; the frontend only gets status and expiry.
- **Redirect:** production needs HTTPS and the app is local `http://`, so v1 uses a **paste-back flow**. It's used once per bank roughly every 180 days.
  1. The Update panel calls `POST /bank-sync/connections` and gets the bank URL. The backend stores `state` (random, single use, 15-min TTL).
  2. You do SCA and land on the registered HTTPS redirect. That's `https://localhost:8443/...` if Enable Banking accepts it (the browser shows a dead page, which is fine), otherwise a static page you own.
  3. You paste the full landing URL into the panel. The backend parses `code` + `state`, verifies `state`, and calls `complete_link`.

  A local HTTPS listener that automates step 3 is possible later. It isn't worth a self-signed-cert setup for two clicks a year.

### 4.5 Scheduler and consent
- `services/bank_sync/sync.py` (`run_bank_sync`) is shared by `POST /bank-sync/sync` and the scheduler, exactly like `run_email_sync`.
- The scheduler reuses the email scheduler's slot logic (`parse_times`, `latest_slot`, `is_due`), which I'd extract to a small shared helper.
- `BANK_SYNC_TIMES` defaults to **two slots** (e.g. `08:00,20:00`). That keeps unattended fetches under the 4-a-day limit with room for retries.
- **Manual "Sync now"** is attended: it sends PSU headers from the browser request, if the spike shows the banks accept a local IP. Otherwise it's unattended too.
- **Fetch window:** `max(watermark + 1, last_success − 5 days) .. today`. The overlap absorbs late-booking rows, and dedup by `external_id` makes re-fetching free.
- **Per-connection status** lives on `bank_connections`: `last_run_at`, `last_ok`, `last_error`, `valid_until`, and `status` (`active | expired | revoked | error`).
- **Errors:**
  - `ConsentExpired` → status `expired`, stop fetching that connection.
  - `RateLimited` → skip until the next slot (not the 15-min retry).
  - `ProviderUnavailable` → normal 15-min retry.
- **Isolation:** a failed connection never blocks the other one, nor anything else in the app.
- **Needs attention gets two new checks:**
  - `bank_consent`: expires within 14 days, or already expired/revoked. Inline action: "Reconnect", which starts the paste-back flow.
  - `bank_sync_failing`: no successful sync in over 48 h on an active connection.

  Keys embed `valid_until` / `last_ok_at`, so dismissals resurface correctly.

### 4.6 What "never load-bearing" means concretely
- With no `ENABLEBANKING_*` config, the bank-sync endpoints return 503 and the scheduler is a no-op. The Update panel hides the section, the same as the email feature.
- Statement and CSV import code is untouched apart from the supersede generalisation and the Revolut fee fix.
- If the provider disappears, delete the connection rows (or leave them `error`). Existing `bank_sync` rows stay valid transactions; they're not provisional. Upload resumes from the watermark.
- No other module imports from `services/bank_sync/` except its router and the scheduler start in the lifespan.

### 4.7 Tests
- **Adapter:** recorded and anonymized spike payloads as fixtures. Cover the sign from CRDT/DBIT, the BOOK-only filter, pagination with empty pages carrying a key, the description composer, the txn_type map, and `EXPIRED_SESSION` → `ConsentExpired` / 429 → `RateLimited`.
- **JWT:** claims, `kid`, expiry, signed with a throwaway test key.
- **Sync service** with a **stub provider**:
  - idempotency: re-running yields 0 new rows, including when a description changes but `external_id` doesn't;
  - an archived row isn't re-imported;
  - the watermark is respected;
  - the fetch window overlaps the last success;
  - one connection failing doesn't stop the other.
- **Overlap:**
  - a statement import archives `bank_sync` rows in its range;
  - a sync after a statement skips covered dates;
  - a sync archives overlapping `email` rows;
  - existing email-supersede tests still pass.
- **Link flow:** a bad, reused or expired `state` is rejected; the callback maps accounts.
- **Attention:** consent expiring/expired, sync failing.
- **Graceful degradation:** with no config, the endpoints return 503 and the scheduler does nothing.

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| The free tier is closed or limited (the GoCardless precedent) | Design §4.6: nothing depends on the sync. One adapter to swap, and there is currently no free alternative to swap to. |
| A bank returns poor descriptions (generic "Card payment" without a merchant) | A spike go/no-go criterion. Per-bank composer; `creditor.name` + MCC. |
| The bank shortens consent (90 days or less) | Measured in the spike. The attention check gives 14 days' notice. |
| The 4-a-day unattended limit | Two slots by default; rate-limit errors defer to the next slot. |
| An HTTPS redirect for a local app | Paste-back flow, twice a year. |
| Date-field mismatch with statements breaks overlap | The spike picks the date field. The watermark rule is date-based and tolerant. |
| One Redsys session per user per TPP | One connection per bank; reconnect replaces it (revoke the old one first). |
| Real financial data in the spike | Scratch folder outside the repo, deleted after the decision. Fixtures are anonymized. |
