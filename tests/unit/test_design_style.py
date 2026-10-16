import json

import pytest

from ethernity.page_sizes import PaperSize, resolve_paper_size
from ethernity.render.design_style import load_design_style, load_page_template
from ethernity.render.template import Template


def _template():
    return {
        "styles": {"body": {"family": "Helvetica", "size_pt": 10, "color": "#123456"}},
        "documents": {
            "main": {
                "first": {
                    "elements": [
                        {
                            "key": "title",
                            "kind": "text",
                            "box": [15, 15, 180, 10],
                            "text": "{copy_title}",
                            "style": "body",
                        },
                    ]
                }
            }
        },
    }


def test_builtin_styles_expose_template_settings_and_live_capabilities():
    archive = load_design_style("archive")
    assert archive.template.document("main").first.qr_capacity == 12
    assert not archive.capabilities.recovery_first_page_single_section
    assert not archive.capabilities.recovery_kit_index_document
    forge = load_design_style("forge")
    assert forge.capabilities.recovery_first_page_single_section
    assert forge.capabilities.recovery_kit_index_document
    assert load_design_style("sentinel").capabilities.recovery_kit_index_document
    for name in ("ledger", "maritime"):
        style = load_design_style(name)
        assert style.name == name
        assert not style.capabilities.recovery_kit_index_document


def test_style_requires_explicit_artwork(tmp_path):
    (tmp_path / "style.json").write_text('{"name": "custom"}')
    with pytest.raises(ValueError, match="template"):
        load_design_style(tmp_path)


def test_style_accepts_template_and_capabilities(tmp_path):
    (tmp_path / "style.json").write_text(
        json.dumps(
            {
                "name": "custom",
                "template": _template(),
                "capabilities": {"recovery_first_page_single_section": True},
            }
        )
    )
    style = load_design_style(tmp_path)
    assert style.template.styles["body"].size_pt == 10
    assert style.capabilities.recovery_first_page_single_section


def test_component_library_is_shared_and_local_artwork_takes_precedence(tmp_path):
    template = _template()
    title = template["documents"]["main"]["first"]["elements"][0]
    library = {"components": {"heading": [title], "decoration": []}}
    (tmp_path / "cards.json").write_text(json.dumps(library))
    template["documents"]["main"]["first"]["elements"] = [
        {"key": "header", "kind": "group", "box": [0, 0, 0, 0], "ref": "heading"}
    ]
    template["components"] = {"decoration": [title]}
    (tmp_path / "style.json").write_text(
        json.dumps({"name": "custom", "template": template, "component_sources": ["cards.json"]})
    )
    loaded = load_design_style(tmp_path).template
    assert loaded.components["heading"][0].text == "{copy_title}"
    assert len(loaded.components["decoration"]) == 1


@pytest.mark.parametrize(
    "source,library,error",
    (
        ("../cards.json", None, "component_sources"),
        ([], None, "component_sources"),
        ("cards.json", None, "cards.json"),
        ("cards.json", {"components": {}, "extra": True}, "extra"),
        ("cards.json", {"components": {"card": [42]}}, "components"),
        (
            "cards.json",
            {
                "components": {
                    "card": [
                        {"key": "bad", "kind": "text", "box": [0, 0, 1, 1], "style": "missing"}
                    ]
                }
            },
            "unknown text style",
        ),
        (
            "cards.json",
            {
                "components": {
                    "card": [{"key": "bad", "kind": "group", "box": [0, 0, 0, 0], "ref": "card"}]
                }
            },
            "cyclic component",
        ),
    ),
)
def test_invalid_component_library_fails_before_rendering(tmp_path, source, library, error):
    if library is not None:
        (tmp_path / "cards.json").write_text(json.dumps(library))
    path = tmp_path / "style.json"
    path.write_text(
        json.dumps({"name": "custom", "template": _template(), "component_sources": [source]})
    )
    with pytest.raises(ValueError, match=error) as caught:
        load_design_style(tmp_path)
    assert str(path) in str(caught.value)


@pytest.mark.parametrize(
    "change,field",
    (
        ({"header": {}}, "header"),
        ({"capabilities": {"advanced_fallback_layout": True}}, "advanced_fallback_layout"),
        ({"capabilities": {"recovery_kit_index_document": 1}}, "recovery_kit_index_document"),
        ({"capabilities": []}, "capabilities"),
        ({"name": "  "}, "name"),
    ),
)
def test_style_rejects_invalid_settings_with_file_and_field(tmp_path, change, field):
    path = tmp_path / "style.json"
    path.write_text(json.dumps({"name": "custom", "template": _template(), **change}))
    with pytest.raises(ValueError) as caught:
        load_design_style(tmp_path)
    assert str(path) in str(caught.value)
    assert field in str(caught.value)


@pytest.mark.parametrize(
    "field,value",
    (
        ("box", [0, 0, -1, 10]),
        ("box", [0, 0, float("nan"), 10]),
        ("style", "missing"),
        ("fill", "blue"),
        ("font_size", 2),
        ("repeat", 0),
        ("kind", "unknown"),
        ("after", "missing"),
        ("after", "title"),
    ),
)
def test_invalid_components_fail_before_rendering(field, value):
    template = _template()
    template["documents"]["main"]["first"]["elements"][0][field] = value
    with pytest.raises(ValueError):
        Template.model_validate_json(json.dumps(template))


def test_component_cycles_are_rejected():
    template = _template()
    template["components"] = {
        "loop": [
            {"key": "recursive", "kind": "group", "box": [0, 0, 0, 0], "ref": "loop"},
        ]
    }
    with pytest.raises(ValueError, match="cyclic component"):
        Template.model_validate_json(json.dumps(template))


def test_style_rejects_missing_and_invalid_json(tmp_path):
    with pytest.raises(ValueError, match="missing design style file"):
        load_design_style(tmp_path)
    (tmp_path / "style.json").write_text("{")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_design_style(tmp_path)


@pytest.mark.parametrize("name", ("archive", "forge", "ledger", "maritime", "sentinel"))
def test_compact_layout_uses_geometry_and_reuses_design_styles(name):
    style = load_design_style(name)
    for paper in ("A4", "LETTER"):
        assert load_page_template(name, resolve_paper_size(paper)) is style.template
    compact = load_page_template(name, resolve_paper_size("A5"))
    assert compact is load_page_template(name, PaperSize("CUSTOM", "Custom", 148, 210))
    assert compact.reference_size == (148, 210)
    assert (
        compact.document("main").first.qr_capacity
        < style.template.document("main").first.qr_capacity
    )
    assert compact.styles["compact-title"].family == style.template.styles["document-title"].family
    assert compact.styles["compact-title"].color == style.template.styles["document-title"].color
    assert compact.document("shard") is compact.document("signing_key_shard")


def _compact_style(tmp_path, *, overrides=None, source=None):
    payload = {
        "name": "custom",
        "template": _template(),
        "compact_layout": {
            "source": "small.json",
            "below_width_mm": 200,
            "below_height_mm": 270,
            "styles": {"body": {"source": "body", "size_pt": 8}},
            **(overrides or {}),
        },
    }
    (tmp_path / "style.json").write_text(json.dumps(payload))
    if source is not None:
        (tmp_path / "small.json").write_text(json.dumps(source))


def test_external_compact_layout_is_data_only_and_uses_local_source(tmp_path):
    source = _template()
    source["reference_size"] = [148, 210]
    _compact_style(tmp_path, source=source)
    compact = load_page_template(tmp_path, resolve_paper_size("A5"))
    assert compact.reference_size == (148, 210)
    assert compact.styles["body"].size_pt == 8
    assert compact.styles["body"].color == "#123456"


def test_compact_layout_can_reuse_base_components_and_override_them(tmp_path):
    source = _template()
    source["documents"]["main"]["first"]["elements"] = [
        {"key": "card", "kind": "group", "box": [0, 0, 0, 0], "ref": "shared-card"}
    ]
    _compact_style(tmp_path, source=source)
    path = tmp_path / "style.json"
    data = json.loads(path.read_text())
    card = [{"key": "border", "kind": "panel", "box": [10, 10, 100, 30], "fill": "#123456"}]
    data["template"]["components"] = {"shared-card": card}
    path.write_text(json.dumps(data))
    compact = load_page_template(tmp_path, resolve_paper_size("A5"))
    assert compact.components["shared-card"][0].fill == "#123456"

    # A second design supplies an explicit compact replacement for the same component.
    other = tmp_path / "override"
    other.mkdir()
    card[0]["fill"] = "#abcdef"
    _compact_style(other, source={**source, "components": {"shared-card": card}})
    assert (
        load_page_template(other, resolve_paper_size("A5")).components["shared-card"][0].fill
        == "#abcdef"
    )


@pytest.mark.parametrize(
    "overrides,source,error",
    (
        ({}, None, "small.json"),
        ({"source": "../small.json"}, None, "source"),
        ({"below_width_mm": 0}, None, "below_width_mm"),
        ({"styles": {"body": {"source": "missing"}}}, _template(), "unknown style source"),
        ({"styles": {"body": {"source": "body", "size_pt": 3}}}, _template(), "size_pt"),
        ({}, {**_template(), "reference_size": [0, 210]}, "reference_size"),
        ({}, {**_template(), "unknown": True}, "unknown"),
        ({}, {**_template(), "components": []}, "invalid compact layout"),
        ({}, [], "layout must be an object"),
    ),
)
def test_invalid_compact_layout_fails_with_a_source_location(tmp_path, overrides, source, error):
    _compact_style(tmp_path, overrides=overrides, source=source)
    with pytest.raises(ValueError, match=error):
        load_page_template(tmp_path, resolve_paper_size("A5"))


@pytest.mark.parametrize("target", ("missing", "alias"))
def test_invalid_document_references_fail_before_rendering(target):
    template = _template()
    template["documents"]["alias"] = {"use": target}
    with pytest.raises(ValueError, match="document layout"):
        Template.model_validate_json(json.dumps(template))
