from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel, Field
from openai import OpenAIError

from .documents import extract_document, DocumentError, MAX_FILE_BYTES
from .llm import extract_resume_json, extract_vacancy_json


router = APIRouter(prefix="/api/llm", tags=["LLM"])


class VacancyRequest(BaseModel):
    description_text: str = Field(default="", max_length=20000)
    key_skills: list[str] = Field(default_factory=list, max_length=50)
    cloud_consent: bool = False


@router.post("/resume")
async def analyze_resume(
    resume: UploadFile = File(...),
    cloud_consent: bool = Form(False),
):
    if not cloud_consent:
        raise HTTPException(
            status_code=422,
            detail="Необходимо согласие на передачу резюме в OpenAI"
        )

    try:
        data = await resume.read(MAX_FILE_BYTES + 1)

        document = extract_document(
            resume.filename or "",
            data
        )

        result = await extract_resume_json(document)

        return {
            "filename": document["filename"],
            "extraction": result
        }

    except DocumentError as exc:
        raise HTTPException(400, str(exc)) from exc

    except OpenAIError as exc:
        raise HTTPException(
            502, "Ошибка обращения к OpenAI API"
        ) from exc

    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc

    finally:
        await resume.close()


@router.post("/vacancy")
async def analyze_vacancy(data: VacancyRequest):
    if not data.cloud_consent:
        raise HTTPException(
            status_code=422,
            detail="Необходимо согласие на передачу вакансии в OpenAI"
        )

    if not data.description_text.strip() and not data.key_skills:
        raise HTTPException(
            status_code=422,
            detail="Необходимо передать текст вакансии"
        )

    try:
        return await extract_vacancy_json({
            "description_text": data.description_text,
            "key_skills": data.key_skills
        })

    except OpenAIError as exc:
        status = getattr(exc, "status_code", None)
        body = getattr(exc, "body", None)

        code = body.get("code") if isinstance(body, dict) else None

        print(
            f"OpenAI ERROR: "
            f"type={type(exc).__name__}, "
            f"status={status}, "
            f"code={code}",
            flush=True
        )

        raise HTTPException(
            status_code=502,
            detail=f"OpenAI API error: {type(exc).__name__}, "
                f"status={status}, code={code}"
        ) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc