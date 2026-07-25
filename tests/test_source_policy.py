from jpjobs.aggregate import list_sources


def test_linkedin_is_opt_in_and_default_source_count_is_nine():
    sources = {source["name"]: source for source in list_sources()}

    assert sources["linkedin"]["status"] == "experimental"
    assert sum(source["status"] == "active" for source in sources.values()) == 9
