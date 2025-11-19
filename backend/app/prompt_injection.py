"""
Protection against prompt injection attacks.
"""

import re
from typing import Any


INJECTION_PATTERNS = [
    r"(?i)(ignore|disregard|forget|skip).*?(previous|above|system|instructions|prompt|rules)",
    r"(?i)(you are now|act as|pretend to be|roleplay as|you're now)",
    r"(?i)(new instructions|override|replace).*?(system|prompt|instructions)",
    r"(?i)(system|assistant):\s*(you|ignore|forget)",
    r"(?i)(<\|.*?\|>|\[INST\]|\[/INST\]|```system|```prompt)",
    r"(?i)(base64|hex|unicode|encode|decode).*?(system|prompt|instructions)",
    r"(?i)(please|kindly|urgently).*?(ignore|forget|skip|override)",
    r"(?i)(important|critical|urgent).*?(ignore|forget|skip|override)",
    r"(?i)(set|change|modify).*?(system_prompt|system prompt|instructions)",
    r"(?i)(output|return|respond).*?(system|prompt|instructions)",
]


def detect_injection_attempt(text: str) -> tuple[bool, str | None]:
    """
    Detect potential prompt injection attempts.
    Returns (is_suspicious, reason) where reason is None if not suspicious.
    """
    if not text or not isinstance(text, str):
        return (False, None)
    
    text_lower = text.lower()
    
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text):
            return (True, f"Detected potential injection pattern: {pattern}")
    
    if len(text) > 10000:  
        return (True, "Input exceeds maximum length")
    
    if re.search(r'[^\w\s\.,!?;:\-\(\)\[\]{}"\']', text) and len(re.findall(r'[^\w\s\.,!?;:\-\(\)\[\]{}"\']', text)) > len(text) * 0.1:
        return (True, "Unusual character patterns detected")
    
    return (False, None)


def sanitize_input(text: str) -> str:
    """
    Sanitize user input to prevent injection while preserving legitimate content.
    This is a conservative approach - we strip potentially dangerous patterns.
    """
    if not text or not isinstance(text, str):
        return ""
    
    text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', text)
    
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    if len(text) > 10000:
        text = text[:10000]
    
    return text.strip()


def wrap_user_input(text: str, context: str = "user request") -> str:
    """
    Wrap user input with explicit delimiters to prevent injection.
    This makes it clear to the LLM that the content is user data, not instructions.
    """
    sanitized = sanitize_input(text)
    
    delimiter_start = "---BEGIN USER INPUT---"
    delimiter_end = "---END USER INPUT---"
    
    return f"{delimiter_start}\n{context}:\n{sanitized}\n{delimiter_end}"


def validate_history_item(item: dict[str, Any]) -> tuple[bool, str | None]:
    """
    Validate a history item for injection attempts.
    Returns (is_valid, error_message).
    """
    if not isinstance(item, dict):
        return (False, "History item must be a dictionary")
    
    question = item.get("question", "")
    answer = item.get("answer", "")
    
    is_suspicious, reason = detect_injection_attempt(str(question))
    if is_suspicious:
        return (False, f"Question contains suspicious content: {reason}")
    
    is_suspicious, reason = detect_injection_attempt(str(answer))
    if is_suspicious:
        return (False, f"Answer contains suspicious content: {reason}")
    
    if len(str(question)) > 10000 or len(str(answer)) > 10000:
        return (False, "History item exceeds maximum length")
    
    return (True, None)

