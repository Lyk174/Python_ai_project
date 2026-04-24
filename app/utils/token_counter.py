# app/utils/token_counter.py
import tiktoken
from typing import List, Dict, Any

def count_tokens(messages: list[Dict[str,Any]],model: str = "gpt-3.5-turbo" ) -> int:
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")

    num_tokens = 0
    for message in messages:
        num_tokens +=4
        for key,value in message.items():
            num_tokens +=len(encoding.encode(str(value)))
            if key == "name":
                num_tokens += -1
    num_tokens +=2
    return num_tokens