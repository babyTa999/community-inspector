import unittest
from classifier import ClassificationResult, MessageClassifier


class MessageClassifierTests(unittest.TestCase):
    def test_extract_fields_regex_extracts_known_source(self) -> None:
        classifier = MessageClassifier(api_key="test-key", base_url="https://api.example.com")
        payload = '{"category":"Problem","translated_zh":"问题","known_status":"known","known_source":"https://github.com/example-org/ProductA/issues","rationale":"test"}'
        result = classifier._extract_fields_regex(payload)
        self.assertEqual(result.get("known_source"), "https://github.com/example-org/ProductA/issues")

    def test_parse_result_validates_known_source(self) -> None:
        classifier = MessageClassifier(api_key="test-key", base_url="https://api.example.com")
        # Valid known_source from allowed list
        payload = '{"category":"Problem","translated_zh":"问题","known_status":"known","known_source":"https://github.com/example-org/ProductA/issues","has_reply":false,"solved":false}'
        result = classifier._parse_result(payload, followups=[])
        self.assertEqual(result.known_source, "https://github.com/example-org/ProductA/issues")
        # Invalid known_source (not in allowed list) should be empty
        payload2 = '{"category":"Problem","translated_zh":"问题","known_status":"known","known_source":"https://example.com","has_reply":false,"solved":false}'
        result2 = classifier._parse_result(payload2, followups=[])
        self.assertEqual(result2.known_source, "")

    def test_parse_result_uses_regex_fallback_for_known_source(self) -> None:
        classifier = MessageClassifier(api_key="test-key", base_url="https://api.example.com")
        # Malformed JSON that regex can still extract
        payload = '{"category":"Problem","translated_zh":"问题","known_status":"known","known_source":"https://github.com/example-org/ProductA/issues","has_reply":false,"solved":false,}'
        result = classifier._parse_result(payload, followups=[])
        self.assertEqual(result.known_source, "https://github.com/example-org/ProductA/issues")


if __name__ == "__main__":
    unittest.main()
