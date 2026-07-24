data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${local.name_prefix}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "app" {
  statement {
    sid     = "ReadRuntimeEnvironment"
    effect  = "Allow"
    actions = ["ssm:GetParameter"]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.runtime_env_parameter_name}",
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.google_live_code_parameter_name}",
    ]
  }

  statement {
    sid       = "ReadApplicationDatabaseCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app_database.arn]
  }

  statement {
    sid    = "ListApplicationBuckets"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.clean.arn,
      aws_s3_bucket.quarantine.arn,
    ]
  }

  statement {
    sid    = "UseCleanRuntimeObjects"
    effect = "Allow"
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.clean.arn}/canonical/*",
    ]
  }

  statement {
    sid    = "UseReportStagingObjects"
    effect = "Allow"
    actions = [
      "s3:DeleteObjectVersion",
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.clean.arn}/staging/canonical/reports/*",
    ]
  }

  statement {
    sid       = "DeleteVersionedCleanUploads"
    effect    = "Allow"
    actions   = ["s3:DeleteObjectVersion"]
    resources = ["${aws_s3_bucket.clean.arn}/canonical/uploads/*"]
  }

  statement {
    sid       = "ListPermanentCleanupVersions"
    effect    = "Allow"
    actions   = ["s3:ListBucketVersions"]
    resources = [aws_s3_bucket.clean.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "canonical/uploads/*",
        "staging/canonical/reports/*",
      ]
    }
  }

  statement {
    sid    = "UseQuarantineRuntimeObjects"
    effect = "Allow"
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.quarantine.arn}/canonical/*",
    ]
  }

  statement {
    sid     = "ReadPinnedDeploymentArtifacts"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = [
      "${aws_s3_bucket.clean.arn}/_deploy/*",
      "${aws_s3_bucket.clean.arn}/_rag-seed/*",
    ]
  }

  statement {
    sid     = "DenyDeploymentArtifactMutation"
    effect  = "Deny"
    actions = ["s3:DeleteObject", "s3:DeleteObjectVersion", "s3:PutObject"]
    resources = [
      "${aws_s3_bucket.clean.arn}/_deploy/*",
      "${aws_s3_bucket.clean.arn}/_rag-seed/*",
    ]
  }

  statement {
    sid       = "LoginToEcr"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PullRuntimeImages"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [
      aws_ecr_repository.backend.arn,
      aws_ecr_repository.frontend.arn,
    ]
  }

  statement {
    sid    = "WriteOperationalHealthLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.operational_health.arn}:*"]
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "${local.name_prefix}-runtime"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app.json
}

resource "aws_iam_instance_profile" "app" {
  name = "${local.name_prefix}-ec2-profile"
  role = aws_iam_role.app.name
}

# The maintenance profile is never the steady-state EC2 profile. The database
# maintenance script stops containers, swaps to this profile for bootstrap and
# migrations, then restores the runtime profile in a finally block. This keeps
# RDS master credentials out of the runtime role and runtime env.
resource "aws_iam_role" "database_maintenance" {
  name               = "${local.name_prefix}-database-maintenance-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy_attachment" "database_maintenance_ssm_core" {
  role       = aws_iam_role.database_maintenance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "database_maintenance" {
  statement {
    sid       = "ReadRotatingRdsMasterCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_db_instance.postgres.master_user_secret[0].secret_arn]
  }

  statement {
    sid    = "ManageApplicationDatabaseCredential"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:PutSecretValue",
    ]
    resources = [aws_secretsmanager_secret.app_database.arn]
  }

  statement {
    sid     = "ReadRuntimeEnvironmentForMigration"
    effect  = "Allow"
    actions = ["ssm:GetParameter"]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.runtime_env_parameter_name}",
    ]
  }

  statement {
    sid       = "LoginToEcr"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PullMigrationImage"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.backend.arn]
  }
}

resource "aws_iam_role_policy" "database_maintenance" {
  name   = "${local.name_prefix}-database-maintenance"
  role   = aws_iam_role.database_maintenance.id
  policy = data.aws_iam_policy_document.database_maintenance.json
}

resource "aws_iam_instance_profile" "database_maintenance" {
  name = "${local.name_prefix}-database-maintenance-profile"
  role = aws_iam_role.database_maintenance.name
}
