"""A bounded backend-only DeepSeek connectivity client."""

import http.client
import json
import os
import re
import ssl
from dataclasses import dataclass
from typing import Callable


HOST = "api.deepseek.com"
PATH = "/chat/completions"
DEFAULT_MODEL = "deepseek-flash"
MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
MAX_RESPONSE_BYTES = 128 * 1024


@dataclass
class DeepSeekError(RuntimeError):
    code: str
    safe_message: str
    status_code: int = 502

    def __str__(self) -> str:
        return self.safe_message


def connection_status(config_error: str | None = None) -> dict[str, object]:
    model = os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    valid_model = bool(MODEL_PATTERN.fullmatch(model))
    configured = bool(os.getenv("DEEPSEEK_API_KEY", "").strip()) and valid_model and not config_error
    return {
        "provider": "DeepSeek",
        "configured": configured,
        "model": model if valid_model else DEFAULT_MODEL,
        "config_error": "后端本地配置无法读取，请检查 backend/.env 后重启后端。" if config_error else
                        "DEEPSEEK_MODEL 格式无效，请检查 backend/.env 后重启后端。" if not valid_model else None,
        "key_exposed": False,
        "test_sends_personal_data": False,
    }


def _safe_http_error(status: int) -> DeepSeekError:
    messages = {
        400: ("invalid_request", "DeepSeek 拒绝了请求，请检查模型配置。", 502),
        401: ("authentication_failed", "DeepSeek 密钥无效，请检查 backend/.env 后重启后端。", 400),
        402: ("insufficient_balance", "DeepSeek API 余额不足，请充值后再试。", 400),
        422: ("invalid_parameters", "DeepSeek 模型或请求参数不可用，请检查配置。", 400),
        429: ("rate_limited", "DeepSeek 请求过于频繁，请稍后手动重试。", 429),
        500: ("provider_error", "DeepSeek 服务暂时异常，请稍后手动重试。", 502),
        503: ("provider_overloaded", "DeepSeek 服务繁忙，请稍后手动重试。", 503),
    }
    code, message, local_status = messages.get(status, ("provider_error", "DeepSeek 连接失败，请稍后重试。", 502))
    return DeepSeekError(code, message, local_status)


def _chat_completion(payload: dict, config_error: str | None = None, *,
                     connection_factory: Callable[..., object] | None = None,
                     timeout_seconds: int = 30) -> tuple[dict, str]:
    status = connection_status(config_error)
    if not status["configured"]:
        message = status["config_error"] or "尚未配置 DeepSeek 密钥，请填写 backend/.env 后重启后端。"
        raise DeepSeekError("not_configured", str(message), 400)
    key = os.environ["DEEPSEEK_API_KEY"].strip()
    model = str(status["model"])
    request_payload = json.dumps({
        **payload, "model": model,
    }, ensure_ascii=False).encode("utf-8")
    factory = connection_factory or (lambda host, timeout: http.client.HTTPSConnection(
        host, timeout=timeout, context=ssl.create_default_context()
    ))
    connection = factory(HOST, timeout_seconds)
    try:
        connection.request("POST", PATH, body=request_payload, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": "resume-tailor/agent-v1",
        })
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise DeepSeekError("response_too_large", "DeepSeek 返回内容超过安全读取上限。")
        if response.status != 200:
            raise _safe_http_error(response.status)
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise DeepSeekError("invalid_response", "DeepSeek 已响应，但返回格式无效。") from error
        if not isinstance(result, dict):
            raise DeepSeekError("invalid_response", "DeepSeek 已响应，但返回格式无效。")
        return result, model
    except DeepSeekError:
        raise
    except TimeoutError as error:
        raise DeepSeekError("timeout", "DeepSeek 连接超时；未自动重试，请稍后手动操作。", 504) from error
    except (OSError, http.client.HTTPException) as error:
        raise DeepSeekError("network_error", "无法连接 DeepSeek 官方接口，请检查网络后再试。") from error
    finally:
        connection.close()


def _usage(result: dict) -> dict[str, int]:
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    return {name: usage.get(name) for name in ("prompt_tokens", "completion_tokens", "total_tokens")
            if isinstance(usage.get(name), int)}


def test_connection(config_error: str | None = None, *, connection_factory: Callable[..., object] | None = None,
                    timeout_seconds: int = 30) -> dict[str, object]:
    result, model = _chat_completion({
        "messages": [
            {"role": "system", "content": "This is a connectivity test. Do not process resumes, jobs, or personal data."},
            {"role": "user", "content": "Reply with exactly: CONNECTED"},
        ],
        "thinking": {"type": "disabled"}, "max_tokens": 16, "stream": False,
    }, config_error, connection_factory=connection_factory, timeout_seconds=timeout_seconds)
    try:
        confirmation = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise DeepSeekError("invalid_response", "DeepSeek 已响应，但连接测试结果格式无效。") from error
    if not isinstance(confirmation, str) or confirmation.strip().upper() != "CONNECTED":
        raise DeepSeekError("unexpected_response", "DeepSeek 已响应，但没有返回预期的连接确认。")
    return {"status": "connected", "provider": "DeepSeek", "model": result.get("model") or model,
            "message": "连接成功。本次仅发送固定测试文字，不含简历、JD 或个人事实。",
            "usage": _usage(result)}


def json_completion(messages: list[dict[str, str]], config_error: str | None = None, *,
                    connection_factory: Callable[..., object] | None = None,
                    timeout_seconds: int = 60, max_tokens: int = 1800) -> tuple[dict, dict[str, object]]:
    result, model = _chat_completion({
        "messages": messages, "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"}, "max_tokens": max_tokens, "stream": False,
    }, config_error, connection_factory=connection_factory, timeout_seconds=timeout_seconds)
    try:
        choice = result["choices"][0]
        if choice.get("finish_reason") == "length":
            raise DeepSeekError("output_truncated", "DeepSeek 输出被截断，未生成候选；请缩小上下文后重试。")
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekError("empty_response", "DeepSeek 返回了空内容；未自动重试，请手动再试一次。")
        output = json.loads(content)
    except DeepSeekError:
        raise
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise DeepSeekError("invalid_response", "DeepSeek 返回的候选不是有效 JSON，未保存任何内容。") from error
    if not isinstance(output, dict):
        raise DeepSeekError("invalid_response", "DeepSeek 返回的候选结构无效，未保存任何内容。")
    return output, {"provider": "DeepSeek", "model": result.get("model") or model, "usage": _usage(result)}
