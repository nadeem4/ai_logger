import loglens


def test_version_matches_installed_package_metadata():
    assert loglens.__version__ == "0.1.0"
