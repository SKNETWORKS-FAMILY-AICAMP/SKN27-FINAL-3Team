ARG ELASTICSEARCH_VERSION=8.19.17
ARG ELASTICSEARCH_IMAGE_REF=docker.elastic.co/elasticsearch/elasticsearch:${ELASTICSEARCH_VERSION}
FROM ${ELASTICSEARCH_IMAGE_REF}

# Korean analyzer for BM25/Nori retrieval experiments.
RUN elasticsearch-plugin install --batch analysis-nori
