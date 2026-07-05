import json

import slr_gui


class DummyVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def make_gui_shell():
    gui = object.__new__(slr_gui.SLRAutomationGUI)
    gui.pdf_folder = DummyVar("pdfs")
    gui.output_folder = DummyVar("output")
    gui.api_key = DummyVar("secret-key")
    gui.max_workers = DummyVar(3)
    gui.rate_limit_delay = DummyVar(1.0)
    gui.parallel_proc = DummyVar(True)
    gui.cache_enabled = DummyVar(True)
    gui.two_stage = DummyVar(False)
    gui.llm_provider = DummyVar("OpenAI")
    gui.llm_model = DummyVar("gpt-4o-mini")
    gui.llm_base_url = DummyVar("")
    gui.criteria_status = DummyVar("")
    gui.advanced_config = {"max_retries": 3}
    gui.screening_prompt = "screening"
    gui.extraction_prompt = "extraction"
    gui.extraction_fields = ["title"]
    gui._legacy_api_key_ignored = False
    gui._api_key_persisted_securely = False
    gui._on_provider_changed = lambda event=None: None
    gui._set_status = lambda text, style="": setattr(gui, "last_status", text)
    return gui


def test_settings_dict_does_not_persist_api_key():
    gui = make_gui_shell()

    settings = gui._settings_dict()

    assert "api_key" not in settings
    assert settings["llm_provider"] == "OpenAI"
    assert settings["llm_model"] == "gpt-4o-mini"
    assert "llm_base_url" in settings


def test_old_settings_api_key_is_ignored_and_removed_on_save(tmp_path, monkeypatch):
    gui = make_gui_shell()
    gui.api_key.set("")
    monkeypatch.setattr(slr_gui, "_load_api_key_from_secure_store", lambda provider: "")
    monkeypatch.setattr(slr_gui, "_save_api_key_to_secure_store", lambda provider, api_key: False)
    monkeypatch.setattr(slr_gui.messagebox, "showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr(slr_gui.messagebox, "showerror", lambda *args, **kwargs: None)

    gui._apply_settings({
        "pdf_folder": "papers",
        "output_folder": "out",
        "api_key": "legacy-plaintext-secret",
        "llm_provider": "OpenAI",
        "llm_model": "gpt-4o-mini",
        "llm_base_url": "http://localhost:1234/v1",
    })

    assert gui.api_key.get() == ""
    assert gui._legacy_api_key_ignored is True

    settings_path = tmp_path / "settings.json"
    gui._save_settings(str(settings_path))
    saved = json.loads(settings_path.read_text(encoding="utf-8"))

    assert "api_key" not in saved
    assert saved["llm_provider"] == "OpenAI"
    assert saved["llm_model"] == "gpt-4o-mini"
    assert saved["llm_base_url"] == "http://localhost:1234/v1"
