# Checker's checks

`run_checks.py` is the gate's checker step (contract in `tools/gate.json`). It builds `stage-N/` from its
Dockerfile, starts one container with `-e PORT` and 2 vCPU / 2 GiB, times the first healthy response, checks the
default port 8080, then runs `tests/` against it and writes JUnit XML to `--out`.

Every check carries `@pytest.mark.item("W-n")` and `# ledger: <ids>`. `items.json` lists the items in force on main
(item -> first stage it binds); only those run. Checker adds an item when its work lands.

Debug against a running service: `run_checks.py --base-url http://127.0.0.1:PORT --stage 1 --out DIR --items W-1,W-2`.
