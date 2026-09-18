from fastapi import FastAPI

app = FastAPI(title="GridWise API")


@app.get("/health")
def health():
    return {
        "status": "ok"
    }