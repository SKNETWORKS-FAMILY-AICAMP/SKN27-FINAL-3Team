data "aws_iam_policy_document" "codepipeline_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codepipeline.amazonaws.com"]
    }
  }
}

resource "aws_s3_bucket" "pipeline_artifacts" {
  count  = var.ci_enabled ? 1 : 0
  bucket = "${local.name_prefix}-pipeline-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "pipeline_artifacts" {
  count                   = var.ci_enabled ? 1 : 0
  bucket                  = aws_s3_bucket.pipeline_artifacts[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "pipeline_artifacts" {
  count  = var.ci_enabled ? 1 : 0
  bucket = aws_s3_bucket.pipeline_artifacts[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "pipeline_artifacts" {
  count  = var.ci_enabled ? 1 : 0
  bucket = aws_s3_bucket.pipeline_artifacts[0].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "pipeline_artifacts" {
  count  = var.ci_enabled ? 1 : 0
  bucket = aws_s3_bucket.pipeline_artifacts[0].id

  depends_on = [aws_s3_bucket_versioning.pipeline_artifacts]

  rule {
    id     = "short-lived-build-artifacts"
    status = "Enabled"
    filter {}

    expiration { days = 14 }
    noncurrent_version_expiration { noncurrent_days = 7 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

resource "aws_iam_role" "codepipeline" {
  count              = var.ci_enabled ? 1 : 0
  name               = "${local.name_prefix}-codepipeline-role"
  assume_role_policy = data.aws_iam_policy_document.codepipeline_assume_role.json
}

data "aws_iam_policy_document" "codepipeline" {
  count = var.ci_enabled ? 1 : 0

  statement {
    sid       = "UseGitHubConnection"
    effect    = "Allow"
    actions   = ["codestar-connections:UseConnection"]
    resources = [var.github_connection_arn]
  }

  statement {
    sid       = "StartPilotBuild"
    effect    = "Allow"
    actions   = ["codebuild:BatchGetBuilds", "codebuild:StartBuild"]
    resources = [aws_codebuild_project.pilot[0].arn]
  }

  statement {
    sid    = "UsePipelineArtifactBucket"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:GetBucketVersioning",
      "s3:PutObject",
    ]
    resources = [
      aws_s3_bucket.pipeline_artifacts[0].arn,
      "${aws_s3_bucket.pipeline_artifacts[0].arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "codepipeline" {
  count  = var.ci_enabled ? 1 : 0
  name   = "${local.name_prefix}-codepipeline"
  role   = aws_iam_role.codepipeline[0].id
  policy = data.aws_iam_policy_document.codepipeline[0].json
}

resource "aws_codepipeline" "pilot" {
  count    = var.ci_enabled ? 1 : 0
  name     = "${local.name_prefix}-source-build"
  role_arn = aws_iam_role.codepipeline[0].arn

  artifact_store {
    location = aws_s3_bucket.pipeline_artifacts[0].bucket
    type     = "S3"
  }

  stage {
    name = "Source"
    action {
      name             = "GitHubDev"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["SourceArtifact"]
      configuration = {
        ConnectionArn    = var.github_connection_arn
        FullRepositoryId = var.github_repository_full_name
        BranchName       = var.github_dev_branch
      }
    }
  }

  stage {
    name = "Build"
    action {
      name             = "BuildAndPushImages"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["SourceArtifact"]
      output_artifacts = ["BuildMetadata"]
      configuration = {
        ProjectName = aws_codebuild_project.pilot[0].name
      }
    }
  }
}

