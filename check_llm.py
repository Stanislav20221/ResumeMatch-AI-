import asyncio
import json
from pathlib import Path

from app.documents import extract_document
from app.llm import extract_resume_json


async def main():
    path = Path('samples/demo_resume.txt')

    document = extract_document(
        path.name,
        path.read_bytes()
    )

    result = await extract_resume_json(document)

    print(json.dumps(
        result,
        ensure_ascii=False,
        indent=2
    ))


asyncio.run(main())