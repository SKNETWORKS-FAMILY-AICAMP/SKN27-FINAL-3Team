data "archive_file" "vision_worker_controller" {
  type        = "zip"
  source_file = "${path.module}/../../deploy/aws-vision/controller.py"
  output_path = "${path.module}/.terraform/vision-worker-controller.zip"
}

resource "aws_sqs_queue" "vision_worker_dlq" {
  count = var.vision_worker_enabled ? 1 : 0

  name                        = "${local.name_prefix}-vision-worker-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  sqs_managed_sse_enabled     = true
}

resource "aws_sqs_queue" "vision_worker" {
  count = var.vision_worker_enabled ? 1 : 0

  name                        = "${local.name_prefix}-vision-worker.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  sqs_managed_sse_enabled     = true
  visibility_timeout_seconds  = 900
  message_retention_seconds   = 1209600
  receive_wait_time_seconds   = 20
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.vision_worker_dlq[0].arn
    maxReceiveCount     = 3
  })
}

resource "aws_ecr_repository" "vision_worker" {
  count = var.vision_registry_enabled ? 1 : 0

  name                 = "${local.name_prefix}/vision-worker"
  image_tag_mutability = "IMMUTABLE"

  encryption_configuration { encryption_type = "AES256" }
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_lifecycle_policy" "vision_worker" {
  count = var.vision_registry_enabled ? 1 : 0

  repository = aws_ecr_repository.vision_worker[0].name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the three newest private Vision worker images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 3
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_subnet" "vision_worker" {
  count = var.vision_worker_enabled ? 1 : 0

  vpc_id                  = aws_vpc.pilot.id
  availability_zone       = data.aws_availability_zones.available.names[0]
  cidr_block              = "10.42.20.0/24"
  map_public_ip_on_launch = false

  tags = { Name = "${local.name_prefix}-private-vision-worker" }
}

resource "aws_route_table" "vision_worker" {
  count = var.vision_worker_enabled ? 1 : 0

  vpc_id = aws_vpc.pilot.id
  tags   = { Name = "${local.name_prefix}-private-vision-worker" }
}

resource "aws_route_table_association" "vision_worker" {
  count = var.vision_worker_enabled ? 1 : 0

  subnet_id      = aws_subnet.vision_worker[0].id
  route_table_id = aws_route_table.vision_worker[0].id
}

resource "aws_security_group" "vision_worker" {
  count = var.vision_worker_enabled ? 1 : 0

  name        = "${local.name_prefix}-vision-worker"
  description = "Private GPU worker: no inbound access"
  vpc_id      = aws_vpc.pilot.id
}

resource "aws_security_group" "vision_worker_endpoints" {
  count = var.vision_worker_enabled ? 1 : 0

  name        = "${local.name_prefix}-vision-endpoints"
  description = "TLS only from the private GPU worker to required AWS endpoints"
  vpc_id      = aws_vpc.pilot.id
}

resource "aws_vpc_security_group_egress_rule" "vision_worker_https" {
  count = var.vision_worker_enabled ? 1 : 0

  security_group_id            = aws_security_group.vision_worker[0].id
  referenced_security_group_id = aws_security_group.vision_worker_endpoints[0].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_security_group_ingress_rule" "vision_worker_endpoints_https" {
  count = var.vision_worker_enabled ? 1 : 0

  security_group_id            = aws_security_group.vision_worker_endpoints[0].id
  referenced_security_group_id = aws_security_group.vision_worker[0].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_endpoint" "vision_worker_s3" {
  count = var.vision_worker_enabled ? 1 : 0

  vpc_id            = aws_vpc.pilot.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.vision_worker[0].id]
}

resource "aws_vpc_endpoint" "vision_worker_interface" {
  for_each = var.vision_worker_enabled ? toset(["ecr.api", "ecr.dkr", "logs", "sqs"]) : toset([])

  vpc_id              = aws_vpc.pilot.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [aws_subnet.vision_worker[0].id]
  security_group_ids  = [aws_security_group.vision_worker_endpoints[0].id]
}

data "aws_iam_policy_document" "vision_worker_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "vision_worker" {
  count = var.vision_worker_enabled ? 1 : 0

  name               = "${local.name_prefix}-vision-worker-role"
  assume_role_policy = data.aws_iam_policy_document.vision_worker_assume_role.json
}

data "aws_iam_policy_document" "vision_worker" {
  count = var.vision_worker_enabled ? 1 : 0

  statement {
    sid       = "ReceiveAndAcknowledgeVisionJobs"
    effect    = "Allow"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.vision_worker[0].arn]
  }

  statement {
    sid     = "ReadSourceAndWriteSafeResults"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = [
      "${aws_s3_bucket.clean.arn}/canonical/uploads/*",
      "${aws_s3_bucket.clean.arn}/vision/aws-queue/v1/*",
    ]
  }

  statement {
    sid       = "PullPrivateVisionImage"
    effect    = "Allow"
    actions   = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [aws_ecr_repository.vision_worker[0].arn]
  }

  statement {
    sid       = "LoginToEcr"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid       = "WritePrivateWorkerLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.vision_worker[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "vision_worker" {
  count = var.vision_worker_enabled ? 1 : 0

  name   = "${local.name_prefix}-vision-worker"
  role   = aws_iam_role.vision_worker[0].id
  policy = data.aws_iam_policy_document.vision_worker[0].json
}

resource "aws_iam_instance_profile" "vision_worker" {
  count = var.vision_worker_enabled ? 1 : 0

  name = "${local.name_prefix}-vision-worker-profile"
  role = aws_iam_role.vision_worker[0].name
}

resource "aws_cloudwatch_log_group" "vision_worker" {
  count = var.vision_worker_enabled ? 1 : 0

  name              = "/skn27/${local.name_prefix}/vision-worker"
  retention_in_days = var.operational_log_retention_days
}

resource "aws_instance" "vision_worker" {
  count = var.vision_worker_enabled ? 1 : 0

  ami                         = var.vision_worker_ami_id
  instance_type               = var.vision_worker_instance_type
  subnet_id                   = aws_subnet.vision_worker[0].id
  associate_public_ip_address = false
  vpc_security_group_ids      = [aws_security_group.vision_worker[0].id]
  iam_instance_profile        = aws_iam_instance_profile.vision_worker[0].name

  user_data = templatefile("${path.module}/vision_worker_user_data.sh.tftpl", {
    aws_region      = var.aws_region
    ecr_registry    = split("/", aws_ecr_repository.vision_worker[0].repository_url)[0]
    image_uri       = "${aws_ecr_repository.vision_worker[0].repository_url}:${var.vision_worker_image_tag}"
    log_group_name  = aws_cloudwatch_log_group.vision_worker[0].name
    queue_url       = aws_sqs_queue.vision_worker[0].url
    result_bucket   = aws_s3_bucket.clean.bucket
    checkpoint_path = var.vision_worker_checkpoint_path
    qwen_model_id   = var.vision_worker_qwen_model_id
    allowed_hosts   = var.vision_worker_allowed_hosts
  })

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 100
    encrypted             = true
    delete_on_termination = false
  }

  tags = { Name = "${local.name_prefix}-vision-worker" }
}

data "aws_iam_policy_document" "vision_worker_controller_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "vision_worker_controller" {
  count = var.vision_worker_enabled ? 1 : 0

  name               = "${local.name_prefix}-vision-controller-role"
  assume_role_policy = data.aws_iam_policy_document.vision_worker_controller_assume_role.json
}

data "aws_iam_policy_document" "vision_worker_controller" {
  count = var.vision_worker_enabled ? 1 : 0

  statement {
    sid       = "DescribePrivateVisionWorker"
    effect    = "Allow"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"]
  }

  statement {
    sid     = "ControlOnlyThePrivateVisionWorker"
    effect  = "Allow"
    actions = ["ec2:StartInstances", "ec2:StopInstances"]
    resources = [
      "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:instance/${aws_instance.vision_worker[0].id}",
    ]
  }

  statement {
    sid       = "ReadVisionQueueDepth"
    effect    = "Allow"
    actions   = ["sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.vision_worker[0].arn]
  }

  statement {
    sid       = "WriteControllerLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "vision_worker_controller" {
  count = var.vision_worker_enabled ? 1 : 0

  name   = "${local.name_prefix}-vision-controller"
  role   = aws_iam_role.vision_worker_controller[0].id
  policy = data.aws_iam_policy_document.vision_worker_controller[0].json
}

resource "aws_lambda_function" "vision_worker_start" {
  count = var.vision_worker_enabled ? 1 : 0

  function_name    = "${local.name_prefix}-vision-worker-start"
  role             = aws_iam_role.vision_worker_controller[0].arn
  handler          = "controller.handler"
  runtime          = "python3.12"
  timeout          = 30
  filename         = data.archive_file.vision_worker_controller.output_path
  source_code_hash = data.archive_file.vision_worker_controller.output_base64sha256

  environment {
    variables = {
      VISION_CONTROLLER_ACTION  = "start"
      VISION_WORKER_INSTANCE_ID = aws_instance.vision_worker[0].id
      AWS_VISION_QUEUE_URL      = aws_sqs_queue.vision_worker[0].url
    }
  }
}

resource "aws_lambda_function" "vision_worker_idle_stop" {
  count = var.vision_worker_enabled ? 1 : 0

  function_name    = "${local.name_prefix}-vision-worker-idle-stop"
  role             = aws_iam_role.vision_worker_controller[0].arn
  handler          = "controller.handler"
  runtime          = "python3.12"
  timeout          = 30
  filename         = data.archive_file.vision_worker_controller.output_path
  source_code_hash = data.archive_file.vision_worker_controller.output_base64sha256

  environment {
    variables = {
      VISION_CONTROLLER_ACTION  = "idle_stop"
      VISION_WORKER_INSTANCE_ID = aws_instance.vision_worker[0].id
      AWS_VISION_QUEUE_URL      = aws_sqs_queue.vision_worker[0].url
    }
  }
}

resource "aws_cloudwatch_event_rule" "vision_worker_start" {
  count = var.vision_worker_enabled ? 1 : 0

  name                = "${local.name_prefix}-vision-worker-start"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "vision_worker_start" {
  count = var.vision_worker_enabled ? 1 : 0

  rule = aws_cloudwatch_event_rule.vision_worker_start[0].name
  arn  = aws_lambda_function.vision_worker_start[0].arn
}

resource "aws_lambda_permission" "vision_worker_start" {
  count = var.vision_worker_enabled ? 1 : 0

  statement_id  = "AllowEventBridgeStart"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.vision_worker_start[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.vision_worker_start[0].arn
}

resource "aws_cloudwatch_event_rule" "vision_worker_idle_stop" {
  count = var.vision_worker_enabled ? 1 : 0

  name                = "${local.name_prefix}-vision-worker-idle-stop"
  schedule_expression = "rate(${var.vision_worker_idle_minutes} minutes)"
}

resource "aws_cloudwatch_event_target" "vision_worker_idle_stop" {
  count = var.vision_worker_enabled ? 1 : 0

  rule = aws_cloudwatch_event_rule.vision_worker_idle_stop[0].name
  arn  = aws_lambda_function.vision_worker_idle_stop[0].arn
}

resource "aws_lambda_permission" "vision_worker_idle_stop" {
  count = var.vision_worker_enabled ? 1 : 0

  statement_id  = "AllowEventBridgeIdleStop"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.vision_worker_idle_stop[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.vision_worker_idle_stop[0].arn
}
