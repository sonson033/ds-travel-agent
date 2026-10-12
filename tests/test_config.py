from travel_agent import config


def test_data_files_exist():
    for path in config.DATA_FILES:
        assert path.is_file(), f"missing: {path}"


def test_calendars_exist():
    for persona_id in ["T1", "T2", "T3"]:
        assert config.calendar_file(persona_id).is_file()


def test_paths_point_to_delivered_folders():
    assert config.DATA_DIR.name == "data"
    assert config.CALENDAR_DIR.name == "calendars"
    assert config.DATA_DIR.parent == config.PROJECT_ROOT
