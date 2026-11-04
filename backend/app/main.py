from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from .data import DataStore
from .llm import LLMError, build_client
from .pipeline import Assistant, PlanningFailed
from .policy import Policy
from .summary import build_summary

store = DataStore()
assistant = Assistant(store, Policy(), build_client())
app = FastAPI(title="Finance Procurement Assistant")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question cannot be blank")
        return value.strip()


def error(status: int, code: str, message: str, retryable: bool) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message, "retryable": retryable}})


@app.exception_handler(LLMError)
def on_llm_error(_: Request, exc: LLMError) -> JSONResponse:
    # Deliberately no silent switch to the stub: the analyst must know what answered them.
    return error(503, "llm_unavailable", "The AI service is unavailable, so no answer was produced.",
                 exc.retryable)


@app.exception_handler(PlanningFailed)
def on_planning_failed(_: Request, __: PlanningFailed) -> JSONResponse:
    return error(502, "planning_failed",
                 "The assistant could not work out how to answer this. Try rephrasing the question.",
                 False)


@app.get("/summary")
def get_summary() -> dict:
    return {**build_summary(store), "llm": assistant.mode}


@app.post("/ask")
def ask(request: AskRequest) -> dict:
    return assistant.ask(request.question)
