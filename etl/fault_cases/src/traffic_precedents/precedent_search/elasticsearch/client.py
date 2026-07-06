from __future__ import annotations

from elasticsearch import Elasticsearch

from ..search_config import ELASTICSEARCH_SETTINGS, ElasticsearchSettings


def get_elasticsearch_client(settings: ElasticsearchSettings = ELASTICSEARCH_SETTINGS) -> Elasticsearch:
    return Elasticsearch(
        settings.host,
        basic_auth=(settings.username, settings.password),
        request_timeout=settings.request_timeout,
        verify_certs=False,
    )
