locals {
  pilot_app_release_enabled = var.ci_enabled && var.pilot_app_release_enabled
}

data "aws_iam_policy_document" "codebuild_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_cloudwatch_log_group" "codebuild" {
  count             = var.ci_enabled ? 1 : 0
  name              = "/aws/codebuild/${local.name_prefix}-pilot"
  retention_in_days = var.ci_log_retention_days
}

resource "aws_iam_role" "codebuild" {
  count              = var.ci_enabled ? 1 : 0
  name               = "${local.name_prefix}-codebuild-role"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
}

data "aws_iam_policy_document" "codebuild" {
  count = var.ci_enabled ? 1 : 0

  statement {
    sid       = "LoginToEcr"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PushPilotImages"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = concat(
      [
        aws_ecr_repository.backend.arn,
        aws_ecr_repository.frontend.arn,
      ],
      var.vision_registry_enabled ? [aws_ecr_repository.vision_worker[0].arn] : [],
    )
  }

  statement {
    sid     = "WriteCodeBuildLogs"
    effect  = "Allow"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "${aws_cloudwatch_log_group.codebuild[0].arn}:*",
    ]
  }

  statement {
    sid     = "ReadPipelineArtifactBucketMetadata"
    effect  = "Allow"
    actions = ["s3:GetBucketAcl", "s3:GetBucketLocation"]
    resources = [
      aws_s3_bucket.pipeline_artifacts[0].arn,
    ]
  }

  statement {
    sid     = "ReadWritePipelineArtifacts"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"]
    resources = [
      "${aws_s3_bucket.pipeline_artifacts[0].arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "codebuild" {
  count  = var.ci_enabled ? 1 : 0
  name   = "${local.name_prefix}-codebuild"
  role   = aws_iam_role.codebuild[0].id
  policy = data.aws_iam_policy_document.codebuild[0].json
}

resource "aws_codebuild_project" "pilot" {
  count          = var.ci_enabled ? 1 : 0
  name           = "${local.name_prefix}-build"
  service_role   = aws_iam_role.codebuild[0].arn
  build_timeout  = 60
  queued_timeout = 60

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_LARGE"
    image                       = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true

    environment_variable {
      name  = "BACKEND_REPOSITORY_URL"
      value = aws_ecr_repository.backend.repository_url
    }
    environment_variable {
      name  = "FRONTEND_REPOSITORY_URL"
      value = aws_ecr_repository.frontend.repository_url
    }
    environment_variable {
      name  = "VISION_REPOSITORY_URI"
      value = var.vision_registry_enabled ? aws_ecr_repository.vision_worker[0].repository_url : ""
    }
    environment_variable {
      name  = "VITE_GOOGLE_CLIENT_ID"
      value = var.frontend_google_client_id
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.codebuild[0].name
      stream_name = "build"
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "buildspec.pilot.yml"
  }
}

resource "aws_cloudwatch_log_group" "pilot_app_release" {
  count             = local.pilot_app_release_enabled ? 1 : 0
  name              = "/aws/codebuild/${local.name_prefix}-pilot-app-release"
  retention_in_days = var.ci_log_retention_days
}

resource "aws_iam_role" "pilot_app_release" {
  count              = local.pilot_app_release_enabled ? 1 : 0
  name               = "${local.name_prefix}-pilot-app-release-role"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
}

data "aws_instance" "pilot_app_release_target" {
  count = local.pilot_app_release_enabled ? 1 : 0

  filter {
    name   = "tag:Name"
    values = ["${local.name_prefix}-app"]
  }
}

data "aws_iam_policy_document" "pilot_app_release" {
  count = local.pilot_app_release_enabled ? 1 : 0

  statement {
    sid     = "WriteReleaseCodeBuildLogs"
    effect  = "Allow"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "${aws_cloudwatch_log_group.pilot_app_release[0].arn}:*",
    ]
  }

  statement {
    sid     = "ReadPipelineSourceArtifactBucketMetadata"
    effect  = "Allow"
    actions = ["s3:GetBucketAcl", "s3:GetBucketLocation"]
    resources = [
      aws_s3_bucket.pipeline_artifacts[0].arn,
    ]
  }

  statement {
    sid     = "ReadPipelineSourceArtifact"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = [
      "${aws_s3_bucket.pipeline_artifacts[0].arn}/*",
    ]
  }

  statement {
    sid     = "SendReleaseCommandToPilot"
    effect  = "Allow"
    actions = ["ssm:SendCommand"]
    resources = [
      data.aws_instance.pilot_app_release_target[0].arn,
      "arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript",
    ]
  }

  statement {
    sid       = "ReadReleaseCommandInvocation"
    effect    = "Allow"
    actions   = ["ssm:GetCommandInvocation"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "pilot_app_release" {
  count  = local.pilot_app_release_enabled ? 1 : 0
  name   = "${local.name_prefix}-pilot-app-release"
  role   = aws_iam_role.pilot_app_release[0].id
  policy = data.aws_iam_policy_document.pilot_app_release[0].json
}

resource "aws_codebuild_project" "pilot_app_release" {
  count          = local.pilot_app_release_enabled ? 1 : 0
  name           = "${local.name_prefix}-pilot-app-release"
  service_role   = aws_iam_role.pilot_app_release[0].arn
  build_timeout  = 30
  queued_timeout = 30

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = false

    environment_variable {
      name  = "PILOT_INSTANCE_ID"
      value = data.aws_instance.pilot_app_release_target[0].id
    }
    environment_variable {
      name  = "BACKEND_REPOSITORY_URL"
      value = aws_ecr_repository.backend.repository_url
    }
    environment_variable {
      name  = "FRONTEND_REPOSITORY_URL"
      value = aws_ecr_repository.frontend.repository_url
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.pilot_app_release[0].name
      stream_name = "release"
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "buildspec.pilot-app-release.yml"
  }
}
