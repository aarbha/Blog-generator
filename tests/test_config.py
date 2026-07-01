from config import Settings


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.ollama_base_url == "http://localhost:11434/v1"
    assert s.writer_model == "qwen2.5:7b"
    assert s.analyzer_model == "qwen2.5:3b"
    assert s.cheap_model == "qwen2.5:1.5b"
    assert s.max_source_chars == 80000
    assert s.writer_timeout == 300
    assert s.analyzer_timeout == 180
    assert s.cache_ttl == 3600
    assert s.search_cache_ttl == 1800


def test_model_selection():
    s = Settings(
        ollama_model_writer="qwen2.5:7b",
        ollama_model_analyzer="qwen2.5:3b",
        ollama_model_cheap="qwen2.5:1.5b",
        _env_file=None,
    )
    assert s.writer_model == "qwen2.5:7b"
    assert s.analyzer_model == "qwen2.5:3b"
    assert s.cheap_model == "qwen2.5:1.5b"


def test_custom_base_url():
    s = Settings(ollama_base_url="http://192.168.1.100:11434/v1", _env_file=None)
    assert s.ollama_base_url == "http://192.168.1.100:11434/v1"


def test_validate_passes():
    s = Settings(_env_file=None)
    s.validate()
