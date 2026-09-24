from src.retriever import TfidfRetriever


def _r(kb):
    r = TfidfRetriever()
    r.index(kb)
    return r


def test_t1_retrieves_deposit_article(kb_articles):
    res = _r(kb_articles).search("I deposited by bank card two hours ago but my balance still shows zero.")
    assert res.sufficient and res.hits[0].article_id == "A1"


def test_top_k_bounded(kb_articles):
    r = _r(kb_articles)
    q = "deposit withdrawal password account locked trading advice"
    for k in (0, 1, 3, 10):
        assert 1 <= len(r.search(q, k).hits) <= 3


def test_deterministic_and_order_independent(kb_articles):
    q = "my withdrawal was declined"
    a = _r(kb_articles).search(q)
    b = _r(list(reversed(kb_articles))).search(q)
    assert a == b


def test_empty_and_short_queries_safe(kb_articles):
    r = _r(kb_articles)
    for q in ["", "  ", "a", "??", "!!!!"]:
        res = r.search(q)
        assert res.hits == [] and not res.sufficient


def test_irrelevant_query_below_threshold(kb_articles):
    res = _r(kb_articles).search("What is the weather like on Mars this weekend?")
    assert not res.sufficient and res.hits == []


def test_stable_tie_breaking(kb_articles):
    from src.models import Article
    twins = [Article(article_id="B2", title="Same", body="identical text here"),
             Article(article_id="B1", title="Same", body="identical text here")]
    res = _r(twins).search("identical text")
    assert [h.article_id for h in res.hits] == ["B1", "B2"]
