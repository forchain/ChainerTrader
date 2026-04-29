## 1. Configuration And Mode Routing

- [x] 1.1 Add an explicit live execution mode option for trader tasks, including `manual_notify` and preserving the existing automatic behavior as the default or documented legacy path.
- [x] 1.2 Add or document local manual-mode starting state inputs, including starting cash/free capital and optional starting position.
- [x] 1.3 Route live trader task operations through a mode boundary before exchange order placement.

## 2. Manual Notification Event Model

- [x] 2.1 Define a structured manual trade notification event with market, strategy, task id, mode, action, side, signal time, signal price, suggested amount/quantity, local cash, local position, and trigger reason fields.
- [x] 2.2 Map operation types into entry/exit notification semantics, including BUY/LONG as entry and SELL/CLOSE as exit.
- [x] 2.3 Include strategy/framework risk references such as stop-loss, take-profit, and risk/reward when available without treating them as submitted exchange orders.

## 3. Manual Mode Runtime Behavior

- [x] 3.1 Implement manual mode so generated operations update local simulated state and send notification events.
- [x] 3.2 Ensure manual mode does not call exchange `new_order` or equivalent order placement APIs.
- [x] 3.3 Ensure manual mode notification decisions do not require exchange account balance reads.
- [x] 3.4 Ensure local stop-loss, take-profit, or reverse-signal exits are rendered as ordinary exit notifications with a trigger reason.

## 4. Email Notification Rendering

- [x] 4.1 Update notification handling to consume current `TraderResult.opts` or the new structured notification event rather than the obsolete `tret.operate` shape.
- [x] 4.2 Render manual-mode email content with clear language that the message is a local strategy recommendation, not an exchange fill confirmation.
- [x] 4.3 Include all required operation fields in entry and exit emails.
- [x] 4.4 Keep notification configuration under `configs/notices/...` and avoid adding credentials or generated outputs to tests.

## 5. Tests And Verification

- [x] 5.1 Add unit tests for manual mode operation-to-notification mapping for entry and exit operations.
- [x] 5.2 Add tests proving manual mode does not call exchange order placement.
- [x] 5.3 Add tests proving manual mode can emit notifications without exchange balance availability.
- [x] 5.4 Add tests for email rendering fields, including market, action, side, amount/quantity, signal time/price, local account state, and trigger reason.
- [x] 5.5 Add a credential-gated end-to-end smoke test using a minimal always-trigger strategy and short-period K-line input to send one real email through the configured notice provider.
- [x] 5.6 Ensure the real-email smoke test is skipped or fails fast with a concrete prerequisite message when SMTP credentials or recipient configuration are missing.
- [x] 5.7 If an inbox SDK/API is available for the configured provider, verify receipt of the test email; otherwise print/send enough message metadata for manual inbox verification.
- [x] 5.8 Run the relevant automated test suite and OpenSpec validation for this change.
