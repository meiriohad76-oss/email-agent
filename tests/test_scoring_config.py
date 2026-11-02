import json

import pytest

from email_article_analyzer.scoring_config import is_custom_scoring_config
from email_article_analyzer.scoring_config import load_scoring_config
from email_article_analyzer.scoring_config import recommended_scoring_config
from email_article_analyzer.scoring_config import save_scoring_config
from email_article_analyzer.scoring_config import validate_scoring_config


def test_scoring_config_round_trip_and_custom_detection(tmp_path):
    path = tmp_path / "research_scoring_config.json"
    config = recommended_scoring_config()
    config["sectors"]["Biotechnology"]["valuation"] = 5
    config["sectors"]["Biotechnology"]["momentum"] = 15

    saved = save_scoring_config(path, config)

    assert load_scoring_config(path) == saved
    assert is_custom_scoring_config(saved) is True
    assert json.loads(path.read_text(encoding="utf-8"))["updated_at"]


def test_scoring_config_rejects_model_that_does_not_total_one_hundred():
    config = recommended_scoring_config()
    config["generic"]["valuation"] = 19

    with pytest.raises(ValueError, match="Generic weights must total 100%"):
        validate_scoring_config(config)


def test_scoring_config_falls_back_to_recommended_when_file_is_invalid(tmp_path):
    path = tmp_path / "research_scoring_config.json"
    path.write_text("not json", encoding="utf-8")

    assert load_scoring_config(path) == recommended_scoring_config()
