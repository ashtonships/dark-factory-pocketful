# Pocketful stage 1

From this directory, build and start the self-contained HTTP service:

```sh
docker build -t pocketful-stage-1 . && docker run --rm -e PORT=18080 -p 18080:18080 pocketful-stage-1
```

The service answers `GET http://127.0.0.1:18080/health`. Change both `18080` values to use another host port. The container keeps its SQLite database on ephemeral local storage and accepts a fixture through `POST /_test/reset`.
