DEFAULT_EXTRACTION_MODEL = "gpt-5.6-luna"
DEFAULT_SUMMARY_MODEL = "gpt-5.6-terra"
DEFAULT_REPORT_MODEL = "gpt-5.6-sol"


def normalize_model_name(value: object, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError("OpenAI model name must be a string")
    normalized = value.strip()
    return normalized or default
