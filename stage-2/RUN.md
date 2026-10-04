# Pocketful stage 2

From this directory, build and start the self-contained HTTP service:

```sh
docker build -t pocketful-stage-2 .
docker run --rm --cpus 2 --memory 2g -e PORT=18080 -p 18080:18080 pocketful-stage-2
```

For isolated verification, replace the port mapping with `--network none` and check through `docker exec` against `http://127.0.0.1:18080/health` inside the container. No runtime operation needs outbound access. The container keeps its SQLite database on ephemeral local storage and accepts a fixture through `POST /_test/reset`.

The API uses JSON unless a UI route is requested with `Accept: text/html`. UI routes are `/`, `/requests`, `/split`, `/signup`, `/login` and `/authorizations`. Assets are self-contained under `/ui/`. UI route placeholders are replaced by Builder-Two's supplied pages.

Every money or hold write and its successful idempotency receipt commit in one `BEGIN IMMEDIATE` transaction. Reads share the writer lock and one SQLite snapshot while deriving expiry at a single clock instant. Stored open holds can remain open internally after their deadline: reads expose `expired`, and spending ignores their remainder. A stored-open expired capture returns `authorization_expired` as specified by D-14.

Export remains `format_version: 1`; import accepts the stage-1 table set, preserving tokens, original receipts and password hashes, adding zero holds and the default 600-second lifetime. Seeded captured authorizations without supplied capture records default to a full captured amount; provided capture history is retained. Lifetimes must produce a representable RFC3339 expiration date.

Every connection uses WAL `synchronous=NORMAL`; transactions remain atomic while container-restart durability is not required. Login hashes outside any transaction and inserts its token in a SQLite writer transaction without the process lock, rechecking the original credentials against reset/import before insertion.

Exports include an internal `authorization_events` table. Captures record their payment time and post-action held remainder; void records its server event time. Export materializes a clock expiry once at `expires_at`, under the writer transaction, without changing stored authorization status or any public response. Older stage-1/2 exports without the table import with an empty event history. Missing legacy release times are not invented. Reset clears event history along with the other state.
