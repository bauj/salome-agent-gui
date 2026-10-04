from salome_agent_gui.module_icons import icon_for

PNG = b"\x89PNG\r\n\x1a\n"


def _install(tmp_path, module, icon="ModuleGeom.png", *, with_file=True, xml=None):
    root = tmp_path / module.upper()
    res = root / "share" / "salome" / "resources" / module
    res.mkdir(parents=True)
    (res / "SalomeApp.xml").write_text(
        xml or f'<document><section name="{module.upper()}">'
               f'<parameter name="name" value="Geometry"/>'
               f'<parameter name="icon" value="{icon}"/></section></document>')
    if with_file:
        (res / icon).write_bytes(PNG)
    return root


def test_icon_is_found_through_the_root_dir_and_salomeapp_xml(tmp_path):
    root = _install(tmp_path, "geom")
    url = icon_for("geom", {"GEOM_ROOT_DIR": str(root)})
    assert url == (root / "share/salome/resources/geom/ModuleGeom.png").as_uri()


def test_module_name_is_case_insensitive(tmp_path):
    root = _install(tmp_path, "smesh", "ModuleMesh.png")
    assert icon_for("SMESH", {"SMESH_ROOT_DIR": str(root)}).endswith("/ModuleMesh.png")


def test_missing_root_dir_variable_gives_none():
    assert icon_for("geom", {}) is None


def test_missing_icon_file_gives_none(tmp_path):
    root = _install(tmp_path, "geom", with_file=False)
    assert icon_for("geom", {"GEOM_ROOT_DIR": str(root)}) is None


def test_broken_xml_gives_none(tmp_path):
    root = _install(tmp_path, "geom", xml="<document><section")
    assert icon_for("geom", {"GEOM_ROOT_DIR": str(root)}) is None


def test_xml_without_icon_parameter_gives_none(tmp_path):
    root = _install(tmp_path, "geom", xml="<document><section name='GEOM'/></document>")
    assert icon_for("geom", {"GEOM_ROOT_DIR": str(root)}) is None


def test_module_name_with_path_characters_gives_none(tmp_path):
    assert icon_for("../geom", {"../GEOM_ROOT_DIR": str(tmp_path)}) is None


def test_icon_falls_back_to_lightapp_xml(tmp_path):
    # SHAPER declares its icon in LightApp.xml only.
    root = _install(tmp_path, "shaper", "shaper.png",
                    xml="<document><section name='SHAPER'/></document>")
    res = root / "share/salome/resources/shaper"
    (res / "LightApp.xml").write_text(
        '<document><section name="SHAPER">'
        '<parameter name="icon" value="shaper.png"/></section></document>')
    assert icon_for("shaper", {"SHAPER_ROOT_DIR": str(root)}) == (res / "shaper.png").as_uri()
