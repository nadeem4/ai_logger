import logscribe


def test_version_matches_installed_package_metadata():
    assert logscribe.__version__ == "0.1.0"
