import os
import asyncio
from typing import List, Union, Iterable
from google.cloud import translate_v3
from google.api_core.retry import Retry, if_exception_type
from google.api_core import exceptions
from google.api_core.client_options import ClientOptions

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = "europe-west1"
API_ENDPOINT = "translate-eu.googleapis.com" # EU host optimisé
MAX_BATCH_SIZE = 128 # maximum conseillé par Google

CLIENT = translate_v3.TranslationServiceClient(
    client_options=ClientOptions(api_endpoint=API_ENDPOINT)
)
PARENT = f"projects/{PROJECT_ID}/locations/{LOCATION}"

RETRY = Retry(
    initial=1.0, maximum=30.0, multiplier=2.0, deadline=120.0,
    predicate=if_exception_type(
        exceptions.DeadlineExceeded,
        exceptions.ServiceUnavailable,
        exceptions.Aborted,
        exceptions.ResourceExhausted,
    ),
)

def _chunks(seq: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

def _translate_batch_sync(batch: List[str], from_source: str, to_target: str) -> List[str]:
    resp = CLIENT.translate_text(
        request=translate_v3.TranslateTextRequest(
            parent=PARENT,
            contents=batch,
            source_language_code=from_source,
            target_language_code=to_target,
            mime_type="text/plain",
            model=None,
        ),
        retry=RETRY,
        timeout=30.0,
    )
    return [t.translated_text for t in resp.translations]


async def translate(texts: Union[str, List[str]], from_source: str, to_target: str) -> List[str]:
    if isinstance(texts, str):
        texts = [texts]
    elif not isinstance(texts, list) or not all(isinstance(x, str) for x in texts):
        raise TypeError("texts doit être str ou List[str]")

    batches = list(_chunks(texts, MAX_BATCH_SIZE))
    tasks = [asyncio.to_thread(_translate_batch_sync, batche, from_source, to_target) for batche in batches]
    results_nested = await asyncio.gather(*tasks)

    return [txt for batch in results_nested for txt in batch]
