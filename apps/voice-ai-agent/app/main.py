from fastapi import FastAPI
from app.graph import graph

app = FastAPI(
    title="Voice AI Agent",
    version="0.1.0",
)


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/test")
async def test():
    result = graph.invoke(
        {"message": "Say hello in one sentence."},
        config={"configurable": {"thread_id": "demo"}}
    )

    return result