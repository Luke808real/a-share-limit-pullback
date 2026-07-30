from __future__ import annotations

from pydantic import BaseModel

from limit_pullback.cli import main
from limit_pullback.models.base import DomainModel


def _all_model_subclasses(cls):
    direct = cls.__subclasses__()
    return direct + [
        nested
        for child in direct
        for nested in _all_model_subclasses(child)
    ]


def test_all_domain_and_config_models_forbid_extra_fields():
    models = {
        model
        for model in _all_model_subclasses(DomainModel)
        if issubclass(model, BaseModel)
    }
    assert models
    assert all(model.model_config.get("extra") == "forbid" for model in models)


def test_unimplemented_cli_command_is_nonzero_and_side_effect_free(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    try:
        main(["screen"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("unimplemented command unexpectedly succeeded")

    assert tuple(tmp_path.iterdir()) == ()
