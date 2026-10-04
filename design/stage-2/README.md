# Pocketful stage-2 concepts

Thirty built-in image-generation concepts: five screen groups, three directions (A/B/C), desktop and phone. The auth group contains separate labelled login and signup route previews. Desktop PNG exports are 1280 pixels wide; phone PNG exports are 375 pixels wide. These are design drawings, not browser screenshots or proof of responsive implementation. Component-state samples are alternatives for review and must not be rendered together in the product.

## Shared visual system

System sans-serif type; warm ivory canvas (#F6F5F0), ink (#123B35), teal primary controls (#136C63), white supporting surfaces, 8px spacing rhythm and restrained 12px corners. Available funds lead; total and held are secondary. Green denotes completion, red refusal, amber an unknown payment outcome, and muted mauve held money. Preserve visible labels, strong contrast, focus rings, full-width narrow-screen inputs and at least 44px touch controls in implementation. Use one consistent navigation arrangement across routes after the pick.

## Concepts and states

| Screen / concept | Idea and illustrated states | Desktop | Phone |
|---|---|---|---|
| Home A | Soft modular cards; available/total/held hierarchy, three money forms, payment-only feed; empty, loading, success, refusal, uncertainty. | [Desktop](home-A-desktop.png) | [Phone](home-A-phone.png) |
| Home B | Compact ledger layout with a desktop rail and aligned payment rows; empty, loading, success, refusal, uncertainty. | [Desktop](home-B-desktop.png) | [Phone](home-B-phone.png) |
| Home C | Contrasting teal wallet panel with quiet supporting forms; empty, loading, success, refusal, uncertainty. | [Desktop](home-C-desktop.png) | [Phone](home-C-phone.png) |
| Requests A | Separate incoming/outgoing cards, clear pending/paid/cancelled status and permitted actions; empty, loading, success, refusal. | [Desktop](requests-A-desktop.png) | [Phone](requests-A-phone.png) |
| Requests B | Ruled incoming/outgoing lists with aligned amounts and compact actions; empty, loading, success, refusal. | [Desktop](requests-B-desktop.png) | [Phone](requests-B-phone.png) |
| Requests C | Teal task heading and spacious direction/status rows; empty, loading, success, refusal. | [Desktop](requests-C-desktop.png) | [Phone](requests-C-phone.png) |
| Split A | Card form beside the live ordered share preview, stacked on phone; empty preview, loading, success, refusal. | [Desktop](split-A-desktop.png) | [Phone](split-A-phone.png) |
| Split B | Flat form and ruled preview stressing exact remainder allocation; empty preview, loading, success, refusal. | [Desktop](split-B-desktop.png) | [Phone](split-B-phone.png) |
| Split C | Teal task band and a clear preview-before-submit sequence; empty preview, loading, success, refusal. | [Desktop](split-C-desktop.png) | [Phone](split-C-phone.png) |
| Auth A | Soft standalone login/signup cards with identical input anatomy; empty fields, focus, loading, success, credential refusal. | [Desktop](auth-A-desktop.png) | [Phone](auth-A-phone.png) |
| Auth B | Flat login/signup sections with typography carrying the hierarchy; empty fields, focus, loading, success, credential refusal. | [Desktop](auth-B-desktop.png) | [Phone](auth-B-phone.png) |
| Auth C | Teal branded headers over quiet white login/signup forms; empty fields, focus, loading, success, credential refusal. | [Desktop](auth-C-desktop.png) | [Phone](auth-C-phone.png) |
| Holds A | Open/closed hold cards with receiver capture and payer release controls; empty, loading, success, refusal. | [Desktop](authorizations-A-desktop.png) | [Phone](authorizations-A-phone.png) |
| Holds B | Ledger rows exposing amount, remaining, expiry and status; empty, loading, success, refusal. | [Desktop](authorizations-B-desktop.png) | [Phone](authorizations-B-phone.png) |
| Holds C | Teal task band with prominent available funds and readable hold actions; empty, loading, success, refusal. | [Desktop](authorizations-C-desktop.png) | [Phone](authorizations-C-phone.png) |

The home phone revisions show total **90071992547409.92 EUR**, held **20.00 EUR**, and available **90071992547389.92 EUR**, without abbreviation. The final CSS must fit the inclusive maximum at a real 375px browser viewport; these drawings do not establish that test result. The split example is 10.00 EUR across ada, bob, cy, with shares 3.34 / 3.33 / 3.33 EUR in input order.

## Build constraints and recorded differences

The specification is authoritative where generated artwork differs. Build to the picked composition and visual tokens using the existing `ui-core/` elements and the replaceable `theme.css`; preserve the supplied `data-testid` attributes and behavior.

- Some drawings render visibility as radio-style choices. The existing Public/Private select remains the actual control. A request has no visibility field; omit any extra visibility field illustrated in a request form.
- Signed-in display names may be human formatted, but `current-handle` is the exact lowercase handle without `@` or surrounding words. Activity parties must contain both actual handles; a decorative "You" label alone is insufficient.
- Extra "View all" links, password-eye icons, close icons, duplicated navigation or row subdivisions in art are optional styling suggestions, not new behavior or routes. Keep one navigation system and the existing page structure.
- Uncertainty means an unknown payment result and a safe explicit retry with the unchanged key/body. Ignore generated references to banks, automatic checking, later updates or background polling. No outbound integration exists. Use: "Payment result unknown. Retry with the same details."
- Requests use pay/decline only for pending incoming records, cancel only for pending outgoing records; closed records have no action. Holds use capture only for the receiver of an open unexpired hold, void only for its payer. "Pending" and "uncertain" are different states.
- Holds stay out of the activity feed. Keep every required exact formatted amount in its designated element, and show the required RFC3339 expiry string even alongside a friendlier label.
- Available funds must remain the clearest wallet value after mixing any per-screen picks. The drawings may vary in form density, but the final phone CSS must keep visible labels, readable text and usable touch controls.

## Generation and review

Generated through the built-in image tool only; no image API, key or paid service was called. The associated prompt set is retained in `prompts.json`. Originals remain in Codex's generated-image storage; PNG exports are copied here for the Coordinator and Checker. Auth drafts that introduced unrelated wallet/top-up screens were discarded; only the focused login/signup replacements are delivered. Phone wallet drafts were revised to show the inclusive maximum balance. No interface implementation or stage-folder edit is part of W-D. Checker owns the pick or revision request.
