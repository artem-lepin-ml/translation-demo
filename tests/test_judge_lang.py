from palimpsest import paths
from palimpsest.webapp.judge import judge_one, scoring_system_prompt


class FakeClient:
    def __init__(self):
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))

        class R:
            content = '{"final_score": 7, "summary": "s", "identified_issues": []}'
            usage = None
        return R()


def test_ru_en_prompt_states_languages():
    p = scoring_system_prompt("accuracy", "ru", "en")
    assert p.startswith("You are evaluating a translation from Russian into English.")
    disk = (paths.PROMPTS / "scoring" / "accuracy.md").read_text(encoding="utf-8")
    assert p.endswith(disk)                      # rubric untouched, preamble is a prefix
    assert "This rubric was written" not in p    # adapter only for non-ru->en pairs


def test_other_pair_gets_adapter_preamble():
    p = scoring_system_prompt("accuracy", "de", "fr")
    assert p.startswith("You are evaluating a translation from German into French.")
    assert "This rubric was written for Russian→English." in p


def test_free_text_language_passes_verbatim():
    p = scoring_system_prompt("accuracy", "Serbian", "English")
    assert p.startswith("You are evaluating a translation from Serbian into English.")
    assert "This rubric was written" in p        # Serbian != Russian -> adapter present


def test_user_message_labels_full_names():
    c = FakeClient()
    judge_one(c, "accuracy", "Quelltext", "cible", source_lang="de", target_lang="fr")
    _, user = c.calls[0]
    assert user.startswith("[SOURCE — German]\nQuelltext")
    assert "[TRANSLATION — French]" in user


def test_default_is_ru_en():
    c = FakeClient()
    judge_one(c, "accuracy", "рус", "eng")
    _, user = c.calls[0]
    assert "[SOURCE — Russian]" in user and "[TRANSLATION — English]" in user
