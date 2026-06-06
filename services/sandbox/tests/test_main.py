"""The sandbox entrypoint must at least import cleanly and expose main(). #8"""


def test_main_module_imports_and_exposes_main():
    import agent_cloud_sandbox.__main__ as entry

    assert callable(entry.main)
