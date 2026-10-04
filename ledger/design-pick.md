# W-D design pick (Checker)

Concepts reviewed: `design/stage-2/` at builder commit 57cc82e (30 PNGs, README.md). Judged against stage-2
"Product and visual direction" (entries 1016–1027, 1206, 1221): calm and trustworthy; available funds the clearest
number; status, direction, privacy and money movement readable without raw data; one visual system; usable at
375 px with no horizontal scroll; visible labels, focus and contrast. The specification wins wherever art differs.

## Picks

| Screen | Pick | Why |
|---|---|---|
| Home `/` | **C** (teal wallet panel) | The strongest available-funds hierarchy of the three: a large white figure on the ink-teal panel, with total and held clearly secondary (1019, 1206, 1221). The feed shows direction with an arrow icon and a "→" between the parties. On the phone the labels sit above full-width inputs, which is the safest layout at 375 px. Home B's available figure is barely larger than total, so B fails 1019. |
| Requests `/requests` | **A** (incoming and outgoing cards) | Two clearly titled cards, "Bob → Ada" direction, a status pill, and actions only where they are permitted. It is the calmest of the three and stacks cleanly on the phone. |
| Split `/split` | **A** (form beside a live preview) | The preview sits beside the form before anything is submitted (1072, 1075), with exact per-handle amounts in input order and the remainder rule explained in one line. It stacks on the phone. |
| Login and signup | **C** (teal brand header over a white form) | The only auth concept with a brand anchor. It shares the home's teal surface, so signed-out and signed-in pages read as one product (1017, 1021). |
| Holds `/authorizations` | **A** (open and closed hold cards) | Top navigation like every other pick; an available-first wallet card; direction arrows; remaining and captured amounts; and the RFC 3339 expiry printed under a friendly date (1214). Closed holds are visually separate from open ones. B and C both use a side rail and colour "Outgoing" amber, so neither fits. |

## One system across screens (binding on W-7)

1. **Navigation.** One top bar on every signed-in route: the Pocketful wordmark, then Wallet, Requests, Split and
   Holds (active item tinted), then the user (`current-user`, `current-handle`) and Sign out. On the phone it becomes
   one row of four tabs directly under the header, never a side rail or a floating bottom bar. The art mixes rail,
   top and bottom navigation; build only this one (1027).
2. **Tokens.**
   - Colour: canvas #F6F5F0, ink #123B35, primary #136C63 for buttons and the wallet panel (not the lighter teal
     in the auth art), white surfaces.
   - Spacing and shape: 8 px rhythm, 12 px corners, system sans-serif type, controls at least 44 px tall.
3. **Colour meanings are reserved** (1023):
   - Green means success and red means refused.
   - **Amber is only for an uncertain payment outcome** (`pay-uncertain`).
   - Mauve is only for held money (`wallet-held`, open holds).
   - **Pending request pills must not be amber.** Every concept draws them amber; use a neutral ink-on-ivory or
     teal-tint pill. Incoming and outgoing labels on holds must not be amber either (Holds A phone, B and C do this).
     Use the direction arrow plus a neutral pill.
   - Replace Split A's blue info box with a teal tint; blue is not in the system.
4. **Wallet hierarchy everywhere it appears.** `wallet-available` is the largest money figure on the page.
   `wallet-balance` (total) and `wallet-held` are smaller. `wallet-held` is absent when held is zero (1207).
   - At 375 px the inclusive maximum 90071992547409.92 EUR must fit without horizontal scrolling. Let the figure
     wrap or step down its font size; never truncate it or abbreviate it.
5. **People first, exact where required.** Parties read "ada → bob". `activity-parties-*` must contain both real
   handles; "You" may be added, but it may not replace the handle. Formatted amounts sit exactly in their testid
   elements. A friendly date may sit beside the required RFC 3339 `authorization-expires-*` text, never instead of it.
6. **Forms.**
   - Visible labels above inputs on the phone.
   - Visibility is the Public/Private `<select>` with values `public` and `private` (no radio art). The request form
     has no visibility field.
   - Keep all values after a payment succeeds (1043).
   - Uncertain copy: "Payment result unknown. Retry with the same details."
7. **Captures.** The API default is a final capture.
   - If the UI offers a non-final capture, label it "Keep the rest held" and leave it unchecked by default, so the
     plain action is the final capture.
   - Or show a "Final capture" box that is checked by default.
   - `authorization-capture-amount-*` is pre-filled with the remaining amount (1215).
8. **States.** Give every list a considered empty state and a skeleton loading state (1027). The "component state
   samples" strips in the art are references only; never render them in the product.

## Revision

None requested. These picks plus the eight rules above are enough to build W-7 directly. I will hold the built
screens to them with desktop and 375 px screenshots in the W-7 review.
