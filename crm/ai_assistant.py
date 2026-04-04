"""AI assistance using Ollama (DeepSeek-Coder) and optional Claude API."""
from __future__ import annotations

import json
import os
from typing import Any

import httpx


class AIAssistant:
    """AI assistant for parsing issues and generating responses."""

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "deepseek-coder:6.7b",
        anthropic_api_key: str | None = None,
        mode: str = "local",  # local, api, hybrid
    ):
        """Initialize AI assistant.

        Args:
            ollama_url: Ollama server URL
            ollama_model: Ollama model name
            anthropic_api_key: Anthropic API key (for Claude)
            mode: AI mode - local (Ollama only), api (Claude only), hybrid
        """
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self.anthropic_api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        self.mode = mode

    def _call_ollama(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str | None:
        """Call Ollama API.

        Args:
            prompt: User prompt
            system: System message
            temperature: Temperature for generation
            json_mode: Whether to request JSON output

        Returns:
            Generated text or None if failed
        """
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            response = httpx.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.ollama_model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                    },
                },
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content")
        except Exception as e:
            print(f"Ollama error: {e}")
            return None

    def _call_claude(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.7,
    ) -> str | None:
        """Call Claude API.

        Args:
            prompt: User prompt
            system: System message
            temperature: Temperature for generation

        Returns:
            Generated text or None if failed
        """
        if not self.anthropic_api_key:
            return None

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.anthropic_api_key)

            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=2000,
                temperature=temperature,
                system=system or "",
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            print(f"Claude error: {e}")
            return None

    def parse_issue(self, raw_text: str) -> dict[str, Any] | None:
        """Parse raw issue text into structured data.

        Args:
            raw_text: Raw user feedback/issue text

        Returns:
            Structured data with type, module, severity, etc.
        """
        system = """You are an AI assistant for a CRM system. Parse the user's technical issue/feedback into structured JSON.

The user issues are in English (technical problems about ZimaOS/NAS/Docker/Linux).
Your response should be in Chinese.

Extract the following fields:
- title: A concise summary of the issue (in Chinese)
- type_tag: One of [R=需求/Request, Q=问题/Question, S=信号/Signal, Tips=技巧]
- feature_module: Which module is affected (Files, Docker, Network, System, etc.)
- priority: One of [低, 中, 高, 紧急]
- analysis: Technical analysis of the issue (in Chinese)

Respond ONLY with valid JSON."""

        prompt = f"Parse this issue:\n\n{raw_text}"

        # Try Ollama first if in local or hybrid mode
        if self.mode in ("local", "hybrid"):
            response = self._call_ollama(prompt, system, json_mode=True)
            if response:
                try:
                    # Extract JSON from response
                    json_str = response
                    if "```json" in response:
                        json_str = response.split("```json")[1].split("```")[0]
                    elif "```" in response:
                        json_str = response.split("```")[1].split("```")[0]
                    return json.loads(json_str.strip())
                except json.JSONDecodeError:
                    pass

        # Fall back to Claude if in api or hybrid mode
        if self.mode in ("api", "hybrid") and self.anthropic_api_key:
            response = self._call_claude(prompt, system)
            if response:
                try:
                    json_str = response
                    if "```json" in response:
                        json_str = response.split("```json")[1].split("```")[0]
                    elif "```" in response:
                        json_str = response.split("```")[1].split("```")[0]
                    return json.loads(json_str.strip())
                except json.JSONDecodeError:
                    pass

        return None

    def suggest_knowledge_base(
        self,
        issue_title: str,
        issue_content: str,
        knowledge_base_results: list[dict],
    ) -> dict[str, Any] | None:
        """Suggest knowledge base articles for an issue.

        Args:
            issue_title: Issue title
            issue_content: Issue content
            knowledge_base_results: Vector search results from KB

        Returns:
            Suggestion with matched KB entry and confidence
        """
        system = """You are an AI assistant helping match user issues to knowledge base articles.

Review the issue and the suggested knowledge base articles.
Determine if any KB article is relevant to solving this issue.

Respond with JSON:
{
    "has_match": true/false,
    "kb_id": "id of best matching KB article",
    "confidence": 0.0-1.0,
    "reason": "Why this KB article is relevant (in Chinese)"
}"""

        kb_text = "\n\n".join([
            f"KB {i+1}: {kb['title']}\n{kb['content'][:500]}..."
            for i, kb in enumerate(knowledge_base_results[:3])
        ])

        prompt = f"""Issue: {issue_title}

Content: {issue_content}

Knowledge Base Articles:
{kb_text}

Which KB article is most relevant?"""

        if self.mode in ("local", "hybrid"):
            response = self._call_ollama(prompt, system, json_mode=True)
            if response:
                try:
                    json_str = response
                    if "```json" in response:
                        json_str = response.split("```json")[1].split("```")[0]
                    elif "```" in response:
                        json_str = response.split("```")[1].split("```")[0]
                    return json.loads(json_str.strip())
                except json.JSONDecodeError:
                    pass

        if self.mode in ("api", "hybrid") and self.anthropic_api_key:
            response = self._call_claude(prompt, system)
            if response:
                try:
                    json_str = response
                    if "```json" in response:
                        json_str = response.split("```json")[1].split("```")[0]
                    elif "```" in response:
                        json_str = response.split("```")[1].split("```")[0]
                    return json.loads(json_str.strip())
                except json.JSONDecodeError:
                    pass

        return None

    def generate_response(
        self,
        issue_title: str,
        issue_content: str,
        kb_article: dict | None = None,
    ) -> str | None:
        """Generate a response to the user issue.

        Args:
            issue_title: Issue title
            issue_content: Issue content
            kb_article: Related knowledge base article

        Returns:
            Generated response in Chinese
        """
        system = """You are a technical support engineer for IceWhale (ZimaOS).
The user has submitted a technical issue in English.
Write a helpful response in Chinese.

Guidelines:
- Be professional and friendly
- Acknowledge the issue
- Provide clear steps or solutions
- If using KB article, reference it
- Offer further assistance"""

        kb_text = ""
        if kb_article:
            kb_text = f"\n\nRelated Knowledge Base Article:\n{kb_article['title']}\n{kb_article['content']}"

        prompt = f"""Issue: {issue_title}

Content: {issue_content}{kb_text}

Write a response in Chinese:"""

        # Try Ollama first
        if self.mode in ("local", "hybrid"):
            response = self._call_ollama(prompt, system, temperature=0.8)
            if response:
                return response

        # Fall back to Claude
        if self.mode in ("api", "hybrid") and self.anthropic_api_key:
            response = self._call_claude(prompt, system, temperature=0.8)
            if response:
                return response

        return None


# Global instance
_ai_assistant: AIAssistant | None = None


def get_ai_assistant() -> AIAssistant:
    """Get or create global AI assistant instance."""
    global _ai_assistant
    if _ai_assistant is None:
        _ai_assistant = AIAssistant(
            ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
            ollama_model=os.getenv("OLLAMA_LLM_MODEL", "deepseek-coder:6.7b"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            mode=os.getenv("AI_MODE", "local"),
        )
    return _ai_assistant
