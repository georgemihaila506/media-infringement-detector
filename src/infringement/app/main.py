from fastapi import FastAPI

app = FastAPI(title="Infringement detector")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
