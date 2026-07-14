locals {
  name = "skn27-${var.environment}"
  tags = {
    Project     = "SKN27-FINAL-3Team"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
  public_subnets = {
    a = { cidr = "10.27.0.0/24", az = "${var.aws_region}a" }
    c = { cidr = "10.27.1.0/24", az = "${var.aws_region}c" }
  }
  private_subnets = {
    a = { cidr = "10.27.10.0/24", az = "${var.aws_region}a" }
    c = { cidr = "10.27.11.0/24", az = "${var.aws_region}c" }
  }
}

resource "aws_vpc" "main" {
  cidr_block           = "10.27.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = local.name }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_subnet" "public" {
  for_each                = local.public_subnets
  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.value.az
  cidr_block              = each.value.cidr
  map_public_ip_on_launch = true
  tags                    = { Name = "${local.name}-public-${each.key}" }
}

resource "aws_subnet" "private" {
  for_each          = local.private_subnets
  vpc_id            = aws_vpc.main.id
  availability_zone = each.value.az
  cidr_block        = each.value.cidr
  tags              = { Name = "${local.name}-private-${each.key}" }
}

resource "aws_eip" "nat" {
  for_each = local.public_subnets
  domain   = "vpc"
}

resource "aws_nat_gateway" "main" {
  for_each      = local.public_subnets
  allocation_id = aws_eip.nat[each.key].id
  subnet_id     = aws_subnet.public[each.key].id
  depends_on    = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  for_each = local.private_subnets
  vpc_id   = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[each.key].id
  }
}

resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private[each.key].id
}

resource "aws_security_group" "alb" {
  name   = "${local.name}-alb"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "app" {
  name   = "${local.name}-app"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "data" {
  name   = "${local.name}-data"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
}

resource "aws_kms_key" "data" {
  description             = "${local.name} application data"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_s3_bucket" "frontend" {
  bucket = "${local.name}-frontend-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "objects" {
  bucket = "${local.name}-objects-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "quarantine" {
  bucket = "${local.name}-quarantine-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "objects" {
  bucket = aws_s3_bucket.objects.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "objects" {
  bucket = aws_s3_bucket.objects.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.data.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.data.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id
  rule {
    id     = "quarantine-retention"
    status = "Enabled"
    filter {}
    expiration { days = 7 }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "objects" {
  bucket     = aws_s3_bucket.objects.id
  depends_on = [aws_s3_bucket_versioning.objects]
  rule {
    id     = "report-staging-retention"
    status = "Enabled"
    filter { prefix = "staging/" }
    expiration { days = 1 }
    noncurrent_version_expiration { noncurrent_days = 1 }
  }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "objects" {
  bucket                  = aws_s3_bucket.objects.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "quarantine" {
  bucket                  = aws_s3_bucket.quarantine.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "random_password" "database" {
  length  = 40
  special = false
}

resource "random_password" "redis" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "database" {
  name                    = "${local.name}/database"
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 30
}

resource "aws_secretsmanager_secret_version" "database" {
  secret_id = aws_secretsmanager_secret.database.id
  secret_string = jsonencode({
    username = "skn27_app"
    password = random_password.database.result
  })
}

resource "aws_secretsmanager_secret" "redis" {
  name                    = "${local.name}/redis"
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 30
}

resource "aws_secretsmanager_secret_version" "redis" {
  secret_id     = aws_secretsmanager_secret.redis.id
  secret_string = jsonencode({ auth_token = random_password.redis.result })
}

resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = values(aws_subnet.private)[*].id
}

resource "aws_db_instance" "main" {
  identifier                 = local.name
  engine                     = "postgres"
  engine_version             = "16"
  instance_class             = "db.t4g.medium"
  allocated_storage          = 100
  max_allocated_storage      = 500
  storage_type               = "gp3"
  storage_encrypted          = true
  kms_key_id                 = aws_kms_key.data.arn
  db_name                    = "law_db"
  username                   = "skn27_app"
  password                   = random_password.database.result
  multi_az                   = true
  backup_retention_period    = 14
  backup_window              = "18:00-19:00"
  maintenance_window         = "sun:19:00-sun:20:00"
  deletion_protection        = var.environment == "production"
  skip_final_snapshot        = var.environment != "production"
  final_snapshot_identifier  = var.environment == "production" ? "${local.name}-final" : null
  db_subnet_group_name       = aws_db_subnet_group.main.name
  vpc_security_group_ids     = [aws_security_group.data.id]
  auto_minor_version_upgrade = true
}

resource "aws_elasticache_subnet_group" "main" {
  name       = local.name
  subnet_ids = values(aws_subnet.private)[*].id
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id       = local.name
  description                = "${local.name} progress and rate-limit cache"
  node_type                  = "cache.t4g.small"
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  multi_az_enabled           = true
  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
  auth_token                 = random_password.redis.result
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.data.id]
}

resource "aws_iam_role" "ecs_task" {
  name = "${local.name}-task"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role" "ecs_scanner_task" {
  name = "${local.name}-scanner-task"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role" "ecs_execution" {
  name = "${local.name}-execution"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_secrets" {
  name = "secrets"
  role = aws_iam_role.ecs_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "kms:Decrypt"]
      Resource = [var.app_secret_arn, aws_secretsmanager_secret.database.arn, aws_secretsmanager_secret.redis.arn, aws_kms_key.data.arn]
    }]
  })
}

resource "aws_iam_role_policy" "app_data" {
  name = "application-data"
  role = aws_iam_role.ecs_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.objects.arn}/canonical/uploads/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["${aws_s3_bucket.objects.arn}/canonical/reports/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"]
        Resource = ["${aws_s3_bucket.objects.arn}/staging/canonical/reports/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucketVersions"]
        Resource = [aws_s3_bucket.objects.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = ["staging/canonical/reports/*"]
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = ["${aws_s3_bucket.quarantine.arn}/canonical/uploads/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
        Resource = [aws_kms_key.data.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["es:ESHttpGet", "es:ESHttpPost", "es:ESHttpPut"]
        Resource = ["${aws_opensearch_domain.main.arn}/*"]
      }
    ]
  })
}

resource "aws_iam_role_policy" "scanner_object_promotion" {
  name = "scanner-object-promotion"
  role = aws_iam_role.ecs_scanner_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:DeleteObject"]
        Resource = ["${aws_s3_bucket.quarantine.arn}/canonical/uploads/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"]
        Resource = ["${aws_s3_bucket.objects.arn}/canonical/uploads/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucketVersions"]
        Resource = [aws_s3_bucket.objects.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = ["canonical/uploads/*"]
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
        Resource = [aws_kms_key.data.arn]
      }
    ]
  })
}

resource "aws_opensearch_domain" "main" {
  domain_name    = local.name
  engine_version = "OpenSearch_3.5"

  cluster_config {
    instance_type            = var.opensearch_instance_type
    instance_count           = 2
    zone_awareness_enabled   = true
    dedicated_master_enabled = false
    zone_awareness_config { availability_zone_count = 2 }
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = 100
  }

  encrypt_at_rest {
    enabled    = true
    kms_key_id = aws_kms_key.data.arn
  }
  node_to_node_encryption {
    enabled = true
  }
  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-PFS-2023-10"
  }
  vpc_options {
    subnet_ids         = values(aws_subnet.private)[*].id
    security_group_ids = [aws_security_group.data.id]
  }

  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = aws_iam_role.ecs_task.arn }
      Action    = "es:ESHttp*"
      Resource  = "arn:aws:es:${var.aws_region}:${data.aws_caller_identity.current.account_id}:domain/${local.name}/*"
    }]
  })
}

resource "aws_opensearch_package_association" "nori" {
  package_id  = var.opensearch_nori_package_id
  domain_name = aws_opensearch_domain.main.domain_name
}

resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.data.arn
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = 90
  kms_key_id        = aws_kms_key.data.arn
}

resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

locals {
  common_environment = [
    { name = "DJANGO_DEBUG", value = "0" },
    { name = "DJANGO_DATABASE_ENGINE", value = "postgres" },
    { name = "POSTGRES_HOST", value = aws_db_instance.main.address },
    { name = "POSTGRES_PORT", value = "5432" },
    { name = "POSTGRES_DB", value = "law_db" },
    { name = "POSTGRES_USER", value = "skn27_app" },
    { name = "REDIS_URL", value = "rediss://:${random_password.redis.result}@${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0" },
    { name = "OBJECT_STORAGE_PROVIDER", value = "s3" },
    { name = "OBJECT_STORAGE_BUCKET", value = aws_s3_bucket.objects.id },
    { name = "OBJECT_STORAGE_QUARANTINE_BUCKET", value = aws_s3_bucket.quarantine.id },
    { name = "OBJECT_STORAGE_PREFIX", value = "canonical" },
    { name = "OBJECT_STORAGE_REGION", value = var.aws_region },
    { name = "FILE_UPLOAD_MAX_BYTES", value = "20971520" },
    { name = "FILE_MAX_ATTACHMENTS_PER_REQUEST", value = "20" },
    { name = "REPORT_STAGING_CLEANUP_LIMIT", value = "100" },
    { name = "TEXT_ML_CASE_SEARCH_PROVIDER", value = "opensearch_aws" },
    { name = "TEXT_ML_CASE_SEARCH_OPENSEARCH_HOST", value = "https://${aws_opensearch_domain.main.endpoint}" },
    { name = "AWS_REGION", value = var.aws_region },
    { name = "LEGAL_PROVISION_DB_ENABLED", value = "1" },
  ]
  common_secrets = [
    { name = "DJANGO_SECRET_KEY", valueFrom = "${var.app_secret_arn}:DJANGO_SECRET_KEY::" },
    { name = "APP_JWT_SECRET", valueFrom = "${var.app_secret_arn}:APP_JWT_SECRET::" },
    { name = "GOOGLE_CLIENT_ID", valueFrom = "${var.app_secret_arn}:GOOGLE_CLIENT_ID::" },
    { name = "GOOGLE_CLIENT_SECRET", valueFrom = "${var.app_secret_arn}:GOOGLE_CLIENT_SECRET::" },
    { name = "SUPERVISOR_LLM_API_KEY", valueFrom = "${var.app_secret_arn}:SUPERVISOR_LLM_API_KEY::" },
    { name = "POSTGRES_PASSWORD", valueFrom = "${aws_secretsmanager_secret.database.arn}:password::" },
  ]
  scanner_environment = [
    { name = "DJANGO_DEBUG", value = "0" },
    { name = "DJANGO_DATABASE_ENGINE", value = "postgres" },
    { name = "POSTGRES_HOST", value = aws_db_instance.main.address },
    { name = "POSTGRES_PORT", value = "5432" },
    { name = "POSTGRES_DB", value = "law_db" },
    { name = "POSTGRES_USER", value = "skn27_app" },
    { name = "OBJECT_STORAGE_PROVIDER", value = "s3" },
    { name = "OBJECT_STORAGE_BUCKET", value = aws_s3_bucket.objects.id },
    { name = "OBJECT_STORAGE_QUARANTINE_BUCKET", value = aws_s3_bucket.quarantine.id },
    { name = "OBJECT_STORAGE_PREFIX", value = "canonical" },
    { name = "OBJECT_STORAGE_REGION", value = var.aws_region },
    { name = "AWS_REGION", value = var.aws_region },
    { name = "FILE_SCAN_PROVIDER", value = "clamav" },
    { name = "FILE_SCAN_CLAMAV_HOST", value = "127.0.0.1" },
    { name = "FILE_SCAN_CLAMAV_PORT", value = "3310" },
    { name = "FILE_SCAN_MAX_BYTES", value = "52428800" },
    { name = "FILE_SCAN_TIMEOUT_SECONDS", value = "10" },
    { name = "FILE_SCAN_CLAIM_STALE_AFTER_SECONDS", value = "300" },
    { name = "FILE_SCAN_RETRY_BACKOFF_SECONDS", value = "60" },
    { name = "FILE_RETENTION_PURGE_LIMIT", value = "100" },
  ]
  scanner_secrets = [
    { name = "DJANGO_SECRET_KEY", valueFrom = "${var.app_secret_arn}:DJANGO_SECRET_KEY::" },
    { name = "POSTGRES_PASSWORD", valueFrom = "${aws_secretsmanager_secret.database.arn}:password::" },
  ]
  log_configuration = {
    logDriver = "awslogs"
    options = {
      awslogs-group         = aws_cloudwatch_log_group.app.name
      awslogs-region        = var.aws_region
      awslogs-stream-prefix = "app"
    }
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn
  container_definitions = jsonencode([{
    name             = "api", image = var.app_image, essential = true,
    portMappings     = [{ containerPort = 8000, protocol = "tcp" }],
    environment      = local.common_environment, secrets = local.common_secrets,
    logConfiguration = local.log_configuration
  }])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn
  container_definitions = jsonencode([{
    name             = "worker", image = var.app_image, essential = true,
    command          = ["python", "backend/manage.py", "process_agent_work_items", "--loop", "--limit", "10"],
    environment      = local.common_environment, secrets = local.common_secrets,
    logConfiguration = local.log_configuration
  }])
}

resource "aws_ecs_task_definition" "scanner" {
  family                   = "${local.name}-scanner"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 2048
  memory                   = 4096
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_scanner_task.arn
  container_definitions = jsonencode([
    {
      name        = "scanner", image = var.app_image, essential = true,
      command     = ["python", "backend/manage.py", "process_uploaded_file_scans", "--loop", "--limit", "20", "--purge-limit", "100"],
      environment = local.scanner_environment,
      secrets     = local.scanner_secrets, logConfiguration = local.log_configuration,
      dependsOn   = [{ containerName = "clamav", condition = "HEALTHY" }]
    },
    {
      name             = "clamav", image = "clamav/clamav:stable", essential = true,
      healthCheck      = { command = ["CMD-SHELL", "clamdscan --ping 1 || exit 1"], interval = 30, timeout = 10, retries = 5, startPeriod = 120 },
      logConfiguration = local.log_configuration
    }
  ])
}

resource "aws_lb" "api" {
  name               = substr("${local.name}-api", 0, 32)
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = values(aws_subnet.public)[*].id
}

resource "aws_lb_target_group" "api" {
  name        = substr("${local.name}-api", 0, 32)
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path    = "/api/health/live/"
    matcher = "200"
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.alb_certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_ecs_service" "api" {
  name            = "${local.name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 2
  launch_type     = "FARGATE"
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = values(aws_subnet.private)[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
}

resource "aws_ecs_service" "worker" {
  name            = "${local.name}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 2
  launch_type     = "FARGATE"
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = values(aws_subnet.private)[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }
}

resource "aws_ecs_service" "scanner" {
  name            = "${local.name}-scanner"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.scanner.arn
  desired_count   = 2
  launch_type     = "FARGATE"
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = values(aws_subnet.private)[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = local.name
  description                       = "Private frontend bucket access"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_wafv2_web_acl" "edge" {
  provider = aws.us_east_1
  name     = local.name
  scope    = "CLOUDFRONT"
  default_action {
    allow {}
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }
  rule {
    name     = "aws-common"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-common"
      sampled_requests_enabled   = true
    }
  }
}

resource "aws_cloudfront_distribution" "app" {
  enabled             = true
  aliases             = [var.domain_name]
  default_root_object = "index.html"
  web_acl_id          = aws_wafv2_web_acl.edge.arn

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "frontend"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }
  origin {
    domain_name = var.api_origin_domain_name
    origin_id   = "api"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }
  default_cache_behavior {
    target_origin_id       = "frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }
  }
  ordered_cache_behavior {
    path_pattern           = "/api/*"
    target_origin_id       = "api"
    viewer_protocol_policy = "https-only"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    min_ttl                = 0
    default_ttl            = 0
    max_ttl                = 0
    forwarded_values {
      query_string = true
      headers      = ["Authorization", "Content-Type", "X-Guest-Id", "X-Auth-Session-Id"]
      cookies {
        forward = "all"
      }
    }
  }
  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
  viewer_certificate {
    acm_certificate_arn      = var.cloudfront_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

resource "aws_route53_record" "app" {
  zone_id = var.hosted_zone_id
  name    = var.domain_name
  type    = "A"
  alias {
    name                   = aws_cloudfront_distribution.app.domain_name
    zone_id                = aws_cloudfront_distribution.app.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "api_origin" {
  zone_id = var.hosted_zone_id
  name    = var.api_origin_domain_name
  type    = "A"
  alias {
    name                   = aws_lb.api.dns_name
    zone_id                = aws_lb.api.zone_id
    evaluate_target_health = true
  }
}

resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-alerts"
  kms_master_key_id = aws_kms_key.data.id
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name}-api-5xx"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  dimensions          = { LoadBalancer = aws_lb.api.arn_suffix }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = data.tls_certificate.github.certificates[*].sha1_fingerprint
}

resource "aws_iam_role" "github_deploy" {
  name = "${local.name}-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity",
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn },
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:ref:refs/heads/*"
        }
      }
    }]
  })
}

data "aws_caller_identity" "current" {}
