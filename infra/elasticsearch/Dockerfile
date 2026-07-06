ARG ELASTICSEARCH_VERSION=8.12.1
FROM docker.elastic.co/elasticsearch/elasticsearch:${ELASTICSEARCH_VERSION}

# Korean analyzer for BM25/Nori retrieval experiments.
RUN elasticsearch-plugin install --batch analysis-nori
