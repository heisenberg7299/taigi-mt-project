from unittest.mock import MagicMock, patch

import pytest

from tw_hokkien_tts_pipeline.config import PipelineConfig
from tw_hokkien_tts_pipeline.contextual_disambiguator import (
    MockContextualDisambiguator,
    OllamaContextualDisambiguator,
    OllamaGlossAwareContextualDisambiguator,
    build_contextual_disambiguator,
)


class TestMockContextualDisambiguator:
    def test_picks_first_candidate(self):
        backend = MockContextualDisambiguator()
        result = backend.disambiguate("我心肝頭敢若咧噗噗惝。", "敢", ["kam2", "kann2"])
        assert result.chosen == "kam2"
        assert result.backend_name == "mock"

    def test_empty_candidates_returns_none_with_error(self):
        backend = MockContextualDisambiguator()
        result = backend.disambiguate("句子", "字", [])
        assert result.chosen is None
        assert result.error is not None


class TestOllamaContextualDisambiguatorSingleCandidate:
    def test_single_candidate_skips_llm_call(self):
        backend = OllamaContextualDisambiguator()
        with patch("requests.post") as mock_post:
            result = backend.disambiguate("句子", "字", ["only_one"])
        mock_post.assert_not_called()
        assert result.chosen == "only_one"


class TestOllamaContextualDisambiguatorResponseParsing:
    def _mock_response(self, text: str):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": text}
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    def test_valid_numeric_response_picks_candidate(self):
        backend = OllamaContextualDisambiguator()
        with patch("requests.post", return_value=self._mock_response("2")):
            result = backend.disambiguate("句子", "敢", ["kam2", "kann2"])
        assert result.chosen == "kann2"
        assert result.error is None

    def test_response_with_extra_text_still_extracts_number(self):
        backend = OllamaContextualDisambiguator()
        with patch("requests.post", return_value=self._mock_response("答案是 1。")):
            result = backend.disambiguate("句子", "敢", ["kam2", "kann2"])
        assert result.chosen == "kam2"

    def test_out_of_range_number_returns_none_not_a_guess(self):
        backend = OllamaContextualDisambiguator()
        with patch("requests.post", return_value=self._mock_response("5")):
            result = backend.disambiguate("句子", "敢", ["kam2", "kann2"])
        assert result.chosen is None
        assert "超出候選範圍" in result.error

    def test_non_numeric_response_returns_none_not_a_guess(self):
        backend = OllamaContextualDisambiguator()
        with patch("requests.post", return_value=self._mock_response("我不確定")):
            result = backend.disambiguate("句子", "敢", ["kam2", "kann2"])
        assert result.chosen is None
        assert "找不到數字" in result.error

    def test_connection_error_returns_none_not_a_guess(self):
        import requests

        backend = OllamaContextualDisambiguator()
        with patch("requests.post", side_effect=requests.exceptions.ConnectionError("boom")):
            result = backend.disambiguate("句子", "敢", ["kam2", "kann2"])
        assert result.chosen is None
        assert "連不到 Ollama" in result.error


class TestOllamaGlossAwareContextualDisambiguator:
    def _mock_response(self, text: str):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": text}
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    def test_single_candidate_skips_llm_call(self):
        backend = OllamaGlossAwareContextualDisambiguator()
        with patch("requests.post") as mock_post:
            result = backend.disambiguate("句子", "字", ["only_one"])
        mock_post.assert_not_called()
        assert result.chosen == "only_one"

    def test_prompt_includes_glosses_when_provided(self):
        backend = OllamaGlossAwareContextualDisambiguator()
        glosses = {"kam2": ["怎麼", "敢"], "kann2": ["大約", "大概"]}
        with patch("requests.post", return_value=self._mock_response("1")) as mock_post:
            backend.disambiguate("我心肝頭敢若咧噗噗惝。", "敢", ["kam2", "kann2"], glosses=glosses)
        sent_prompt = mock_post.call_args.kwargs["json"]["prompt"]
        assert "怎麼" in sent_prompt
        assert "大約" in sent_prompt

    def test_missing_gloss_for_a_candidate_is_labeled_honestly(self):
        backend = OllamaGlossAwareContextualDisambiguator()
        glosses = {"kam2": ["怎麼"]}  # kann2 沒有釋義資料
        with patch("requests.post", return_value=self._mock_response("1")) as mock_post:
            backend.disambiguate("句子", "敢", ["kam2", "kann2"], glosses=glosses)
        sent_prompt = mock_post.call_args.kwargs["json"]["prompt"]
        assert "(無釋義資料)" in sent_prompt

    def test_no_glosses_argument_at_all_still_works(self):
        backend = OllamaGlossAwareContextualDisambiguator()
        with patch("requests.post", return_value=self._mock_response("2")):
            result = backend.disambiguate("句子", "敢", ["kam2", "kann2"])
        assert result.chosen == "kann2"

    def test_valid_response_picks_candidate(self):
        backend = OllamaGlossAwareContextualDisambiguator()
        with patch("requests.post", return_value=self._mock_response("2")):
            result = backend.disambiguate("句子", "敢", ["kam2", "kann2"])
        assert result.chosen == "kann2"
        assert result.error is None

    def test_out_of_range_returns_none_not_a_guess(self):
        backend = OllamaGlossAwareContextualDisambiguator()
        with patch("requests.post", return_value=self._mock_response("9")):
            result = backend.disambiguate("句子", "敢", ["kam2", "kann2"])
        assert result.chosen is None

    def test_name_is_distinct_from_romanization_only_backend(self):
        gloss_backend = OllamaGlossAwareContextualDisambiguator()
        plain_backend = OllamaContextualDisambiguator()
        assert gloss_backend.name != plain_backend.name


class TestBuildContextualDisambiguator:
    def test_mock(self):
        config = PipelineConfig(contextual_disambiguator_backend="mock")
        backend = build_contextual_disambiguator(config)
        assert isinstance(backend, MockContextualDisambiguator)

    def test_ollama(self):
        config = PipelineConfig(contextual_disambiguator_backend="ollama")
        backend = build_contextual_disambiguator(config)
        assert isinstance(backend, OllamaContextualDisambiguator)
        assert backend.model_id == "qwen2.5:7b-instruct"

    def test_unknown_raises(self):
        config = PipelineConfig()
        config.contextual_disambiguator_backend = "bogus"
        with pytest.raises(ValueError):
            build_contextual_disambiguator(config)
