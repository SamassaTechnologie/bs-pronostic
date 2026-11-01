"""Fournisseurs d'IA générative (offres gratuites). Les clés restent côté serveur.

* Google Gemini (AI Studio) : offre gratuite sans carte bancaire, sortie JSON contrainte par un schéma.
* Groq : offre gratuite, modèles ouverts très rapides ; sert de secours si Gemini est indisponible.

Aucune réponse n'est simulée : sans clé configurée, l'analyse IA est déclarée « non configurée ».
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

import httpx

from ..config import get_settings

log = logging.getLogger("sam.ai")


class AIError(Exception):
    """Erreur d'un fournisseur d'IA (message lisible en français)."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class _Throttle:
    """Espacement minimal entre deux appels (offres gratuites : quelques requêtes par minute)."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delay = self._last + self.min_interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


class AIProvider:
    name = ""
    label = ""
    website = ""

    def __init__(self, model: str):
        self.model = model

    def generate_json(self, system: str, user: str, schema: dict) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


def _to_gemini_schema(schema: dict) -> dict:
    """Schéma JSON simple → sous-ensemble OpenAPI attendu par Gemini (types en majuscules)."""
    out: dict = {}
    for k, v in schema.items():
        if k == "type":
            out["type"] = str(v).upper()
        elif k == "properties":
            out["properties"] = {name: _to_gemini_schema(sub) for name, sub in v.items()}
        elif k == "items":
            out["items"] = _to_gemini_schema(v)
        elif k in ("required", "enum", "description", "maxItems", "minItems"):
            out[k] = v
    return out


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise AIError("Réponse de l'IA illisible (pas de JSON)", retryable=True)
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise AIError(f"Réponse de l'IA illisible ({exc.msg})", retryable=True) from exc


def _http_error(provider: str, r: httpx.Response) -> AIError:
    try:
        detail = r.json()
        msg = (detail.get("error") or {}).get("message") if isinstance(detail, dict) else None
    except ValueError:
        msg = None
    msg = (msg or r.text or "")[:200]
    if r.status_code == 429:
        return AIError(f"{provider} : quota gratuit momentanément atteint, réessayez plus tard", retryable=True)
    if r.status_code in (401, 403):
        return AIError(f"{provider} : clé API refusée ({msg})")
    if r.status_code >= 500:
        return AIError(f"{provider} : service indisponible ({r.status_code})", retryable=True)
    return AIError(f"{provider} : erreur {r.status_code} ({msg})")


class GeminiProvider(AIProvider):
    name = "gemini"
    label = "Google Gemini"
    website = "https://aistudio.google.com/apikey"
    _throttle = _Throttle(4.5)  # ≈ 13 requêtes/minute au plus

    def __init__(self, key: str, model: str, base_url: str, timeout: float):
        super().__init__(model)
        self._key, self._base, self._timeout = key, base_url.rstrip("/"), timeout

    def generate_json(self, system: str, user: str, schema: dict) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.35, "maxOutputTokens": 8192,  # marge pour la réflexion interne
                                 "responseMimeType": "application/json",
                                 "responseSchema": _to_gemini_schema(schema)},
        }
        self._throttle.wait()
        try:
            r = httpx.post(f"{self._base}/models/{self.model}:generateContent", json=body, timeout=self._timeout,
                           headers={"x-goog-api-key": self._key, "Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            raise AIError(f"Gemini injoignable ({exc.__class__.__name__})", retryable=True) from exc
        if r.status_code != 200:
            raise _http_error("Gemini", r)
        data = r.json()
        cands = data.get("candidates") or []
        if not cands:
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            raise AIError(f"Gemini n'a renvoyé aucune réponse{f' ({reason})' if reason else ''}", retryable=True)
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text:
            raise AIError(f"Réponse Gemini vide ({cands[0].get('finishReason')})", retryable=True)
        return _parse_json(text)


class GroqProvider(AIProvider):
    name = "groq"
    label = "Groq"
    website = "https://console.groq.com/keys"
    _throttle = _Throttle(2.5)

    def __init__(self, key: str, model: str, base_url: str, timeout: float):
        super().__init__(model)
        self._key, self._base, self._timeout = key, base_url.rstrip("/"), timeout

    def generate_json(self, system: str, user: str, schema: dict) -> dict:
        sys_full = (system + "\n\nRéponds uniquement par un objet JSON valide conforme à ce schéma :\n"
                    + json.dumps(schema, ensure_ascii=False))
        body = {"model": self.model, "temperature": 0.35, "max_tokens": 4096,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": sys_full}, {"role": "user", "content": user}]}
        self._throttle.wait()
        try:
            r = httpx.post(f"{self._base}/chat/completions", json=body, timeout=self._timeout,
                           headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as exc:
            raise AIError(f"Groq injoignable ({exc.__class__.__name__})", retryable=True) from exc
        if r.status_code != 200:
            raise _http_error("Groq", r)
        choices = r.json().get("choices") or []
        if not choices:
            raise AIError("Groq n'a renvoyé aucune réponse", retryable=True)
        return _parse_json(choices[0]["message"].get("content") or "")


def configured_providers() -> list[AIProvider]:
    """Fournisseurs utilisables, dans l'ordre de préférence."""
    s = get_settings()
    choice = (s.ai_provider or "auto").lower()
    if choice == "off":
        return []
    out: list[AIProvider] = []
    gem = GeminiProvider(s.gemini_api_key, s.gemini_model, s.gemini_base_url, s.ai_timeout) if s.gemini_api_key else None
    grq = GroqProvider(s.groq_api_key, s.groq_model, s.groq_base_url, s.ai_timeout) if s.groq_api_key else None
    order = [grq, gem] if choice == "groq" else [gem, grq]  # le fournisseur choisi d'abord, l'autre en secours
    return [p for p in order if p is not None]


def provider_info() -> dict:
    provs = configured_providers()
    return {"configured": bool(provs), "provider": provs[0].label if provs else None,
            "model": provs[0].model if provs else None, "fallback": provs[1].label if len(provs) > 1 else None,
            "setup": {"gemini": GeminiProvider.website, "groq": GroqProvider.website}}


def call_with_fallback(system: str, user: str, schema: dict,
                       providers: Optional[list[AIProvider]] = None) -> tuple[dict, AIProvider]:
    errors = []
    for p in providers if providers is not None else configured_providers():
        try:
            return p.generate_json(system, user, schema), p
        except AIError as exc:
            log.warning("IA %s : %s", p.name, exc)
            errors.append(str(exc))
    raise AIError(" ; ".join(errors) or "Aucun fournisseur d'IA configuré")


# ---------------------------------------------------------------------------
# Conversation avec outils (assistant) : l'IA appelle les fonctions du moteur SAM, jamais l'inverse.



def _gemini_chat(p: "GeminiProvider", system: str, history: list[dict], tools: list[dict], run_tool,
                 on_call, max_steps: int) -> str:
    contents = [{"role": "user" if h["role"] == "user" else "model", "parts": [{"text": h["text"]}]}
                for h in history]
    decl = [{"name": t["name"], "description": t["description"], "parameters": _to_gemini_schema(t["parameters"])}
            for t in tools]
    for step in range(max_steps + 1):
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                "tools": [{"functionDeclarations": decl}],
                "toolConfig": {"functionCallingConfig": {"mode": "AUTO" if step < max_steps else "NONE"}},
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 8192}}
        on_call()
        p._throttle.wait()
        try:
            r = httpx.post(f"{p._base}/models/{p.model}:generateContent", json=body, timeout=p._timeout,
                           headers={"x-goog-api-key": p._key, "Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            raise AIError(f"Gemini injoignable ({exc.__class__.__name__})", retryable=True) from exc
        if r.status_code != 200:
            raise _http_error("Gemini", r)
        cands = r.json().get("candidates") or []
        if not cands:
            raise AIError("Gemini n'a renvoyé aucune réponse", retryable=True)
        content = cands[0].get("content") or {}
        parts = content.get("parts") or []
        calls = [x["functionCall"] for x in parts if "functionCall" in x]
        if not calls:
            text = "".join(x.get("text", "") for x in parts if not x.get("thought")).strip()
            if not text:
                raise AIError(f"Réponse Gemini vide ({cands[0].get('finishReason')})", retryable=True)
            return text
        contents.append({"role": "model", "parts": parts})  # renvoyé tel quel (signatures de réflexion)
        results = []
        for c in calls:
            out = run_tool(c.get("name", ""), c.get("args") or {})
            fr = {"name": c.get("name", ""), "response": {"resultat": out}}
            if c.get("id"):
                fr["id"] = c["id"]
            results.append({"functionResponse": fr})
        contents.append({"role": "user", "parts": results})
    raise AIError("Trop d'étapes pour répondre", retryable=True)


def _groq_chat(p: "GroqProvider", system: str, history: list[dict], tools: list[dict], run_tool,
               on_call, max_steps: int) -> str:
    messages = [{"role": "system", "content": system}] + [
        {"role": "user" if h["role"] == "user" else "assistant", "content": h["text"]} for h in history]
    defs = [{"type": "function", "function": t} for t in tools]
    for step in range(max_steps + 1):
        body = {"model": p.model, "temperature": 0.4, "max_tokens": 4096, "messages": messages,
                "tools": defs, "tool_choice": "auto" if step < max_steps else "none"}
        on_call()
        p._throttle.wait()
        try:
            r = httpx.post(f"{p._base}/chat/completions", json=body, timeout=p._timeout,
                           headers={"Authorization": f"Bearer {p._key}"})
        except httpx.HTTPError as exc:
            raise AIError(f"Groq injoignable ({exc.__class__.__name__})", retryable=True) from exc
        if r.status_code != 200:
            raise _http_error("Groq", r)
        choices = r.json().get("choices") or []
        if not choices:
            raise AIError("Groq n'a renvoyé aucune réponse", retryable=True)
        msg = choices[0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            text = (msg.get("content") or "").strip()
            if not text:
                raise AIError("Réponse Groq vide", retryable=True)
            return text
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            out = run_tool(c["function"]["name"], args)
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(out, ensure_ascii=False)})
    raise AIError("Trop d'étapes pour répondre", retryable=True)


def chat_with_tools(system: str, history: list[dict], tools: list[dict], run_tool, on_call,
                    max_steps: int = 5, providers: Optional[list[AIProvider]] = None) -> tuple[str, AIProvider]:
    """Boucle question → appels d'outils SAM → réponse, avec bascule vers le fournisseur de secours."""
    errors = []
    for p in providers if providers is not None else configured_providers():
        try:
            fn = _gemini_chat if isinstance(p, GeminiProvider) else _groq_chat
            return fn(p, system, history, tools, run_tool, on_call, max_steps), p
        except AIError as exc:
            log.warning("Assistant %s : %s", p.name, exc)
            errors.append(str(exc))
    raise AIError(" ; ".join(errors) or "Aucun fournisseur d'IA configuré")
