"""
通义千问模型适配。
对 LangChain 的 ChatTongyi 做流式容错，跳过缺失 choices 的异常帧，避免工具调用场景中断。
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional
from langchain_community.chat_models.tongyi import ChatTongyi, _create_retry_decorator
from langchain_community.llms.tongyi import (
    agenerate_with_last_element_mark,
    check_response,
    generate_with_last_element_mark,
)
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_ollama.chat_models import ChatOllama

DEFAULT_QWEN_MODEL = "qwen3-vl-235b-a22b-thinking"

def _tongyi_resp_has_nonempty_choices(resp: Any) -> bool:
    if not isinstance(resp, dict):
        return False
    out = resp.get("output")
    if not isinstance(out, dict):
        return False
    ch = out.get("choices")
    return isinstance(ch, list) and len(ch) > 0

class SafeStreamChatTongyi(ChatTongyi):
    """跳过 DashScope 流式响应中的空 choices 帧。"""

    def stream_completion_with_retry(self, **kwargs: Any) -> Any:
        # 绑定 tools 时偶发空帧，必须在 subtract_client_response 前过滤。
        retry_decorator = _create_retry_decorator(self)

        @retry_decorator
        def _stream_completion_with_retry(**_kwargs: Any) -> Any:
            responses = self.client.call(**_kwargs)
            prev_resp: Any = None

            for resp in responses:
                if _kwargs.get("stream") and not _kwargs.get("incremental_output", False):
                    resp_copy = json.loads(json.dumps(resp))
                    if resp_copy.get("output") and resp_copy["output"].get("choices"):
                        choice = resp_copy["output"]["choices"][0]
                        message = choice["message"]
                        if isinstance(message.get("content"), list):
                            content_text = "".join(
                                item.get("text", "")
                                for item in message["content"]
                                if isinstance(item, dict)
                            )
                            message["content"] = content_text
                        resp = resp_copy

                    if prev_resp is None:
                        if not _tongyi_resp_has_nonempty_choices(resp):
                            continue
                        delta_resp = resp
                    else:
                        if not _tongyi_resp_has_nonempty_choices(resp):
                            continue
                        try:
                            delta_resp = self.subtract_client_response(resp, prev_resp)
                        except (IndexError, KeyError, TypeError, ValueError):
                            continue
                    prev_resp = resp
                    yield check_response(delta_resp)
                else:
                    yield check_response(resp)

        return _stream_completion_with_retry(**kwargs)

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        params: Dict[str, Any] = self._invocation_params(
            messages=messages, stop=stop, stream=True, **kwargs
        )
        for stream_resp, is_last_chunk in generate_with_last_element_mark(
            self.stream_completion_with_retry(**params)
        ):
            output = stream_resp.get("output")
            if not isinstance(output, dict):
                continue
            choices = output.get("choices")
            if not isinstance(choices, list) or len(choices) == 0:
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or {}
            if (
                choice.get("finish_reason") == "null"
                and isinstance(message, dict)
                and message.get("content") == ""
                and message.get("reasoning_content", "") == ""
                and "tool_calls" not in message
            ):
                continue
            try:
                chunk = ChatGenerationChunk(
                    **self._chat_generation_from_qwen_resp(
                        stream_resp, is_chunk=True, is_last_chunk=is_last_chunk
                    )
                )
            except (IndexError, KeyError, TypeError, ValueError):
                continue
            if run_manager:
                run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        params: Dict[str, Any] = self._invocation_params(
            messages=messages, stop=stop, stream=True, **kwargs
        )
        async for stream_resp, is_last_chunk in agenerate_with_last_element_mark(
            self.astream_completion_with_retry(**params)
        ):
            output = stream_resp.get("output")
            if not isinstance(output, dict):
                continue
            choices = output.get("choices")
            if not isinstance(choices, list) or len(choices) == 0:
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or {}
            if (
                choice.get("finish_reason") == "null"
                and isinstance(message, dict)
                and message.get("content") == ""
                and message.get("reasoning_content", "") == ""
                and "tool_calls" not in message
            ):
                continue
            try:
                chunk = ChatGenerationChunk(
                    **self._chat_generation_from_qwen_resp(
                        stream_resp, is_chunk=True, is_last_chunk=is_last_chunk
                    )
                )
            except (IndexError, KeyError, TypeError, ValueError):
                continue
            if run_manager:
                await run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk

def get_chat_tongyi(model: str = DEFAULT_QWEN_MODEL, *, streaming: bool = True) -> ChatTongyi:
    return SafeStreamChatTongyi(
        model=model,
        streaming=streaming,
        model_kwargs={"enable_thinking": False},
    )

DEFAULT_OLLAMA_MODEL = "qwen3.5:9b"

def get_chat_ollama(model: str = DEFAULT_OLLAMA_MODEL) -> ChatOllama:
    return ChatOllama(model=model, streaming=True)
