from fastapi import FastAPI

app = FastAPI(title="ytm-taste")


@app.get("/")
def read_root():
    return {"status": "ok", "service": "ytm-taste"}
