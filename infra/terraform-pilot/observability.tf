locals {
  operational_metric_namespace = "SKN27/Pilot"
}

resource "aws_cloudwatch_log_group" "operational_health" {
  name              = "/skn27/${local.name_prefix}/operational-health"
  retention_in_days = var.operational_log_retention_days
}

resource "aws_cloudwatch_log_metric_filter" "heartbeat" {
  name           = "${local.name_prefix}-operational-heartbeat"
  pattern        = "{ $.event_type = \"operational_health\" }"
  log_group_name = aws_cloudwatch_log_group.operational_health.name

  metric_transformation {
    name          = "MonitorHeartbeat"
    namespace     = local.operational_metric_namespace
    value         = "1"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "queue_oldest_age" {
  name           = "${local.name_prefix}-queue-oldest-age"
  pattern        = "{ $.event_type = \"operational_health\" }"
  log_group_name = aws_cloudwatch_log_group.operational_health.name

  metric_transformation {
    name          = "QueueOldestAgeSeconds"
    namespace     = local.operational_metric_namespace
    value         = "$.queue.oldest_queued_age_seconds"
    default_value = 0
    unit          = "Seconds"
  }
}

resource "aws_cloudwatch_log_metric_filter" "stale_running" {
  name           = "${local.name_prefix}-stale-running"
  pattern        = "{ $.event_type = \"operational_health\" }"
  log_group_name = aws_cloudwatch_log_group.operational_health.name

  metric_transformation {
    name          = "StaleRunningCount"
    namespace     = local.operational_metric_namespace
    value         = "$.queue.stale_running_count"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "worker_failures" {
  name           = "${local.name_prefix}-worker-failures"
  pattern        = "{ $.event_type = \"operational_health\" }"
  log_group_name = aws_cloudwatch_log_group.operational_health.name

  metric_transformation {
    name          = "RecentWorkerFailureCount"
    namespace     = local.operational_metric_namespace
    value         = "$.worker.recent_failure_count"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "provider_failures" {
  name           = "${local.name_prefix}-provider-failures"
  pattern        = "{ $.event_type = \"operational_health\" }"
  log_group_name = aws_cloudwatch_log_group.operational_health.name

  metric_transformation {
    name          = "RecentProviderFailureCount"
    namespace     = local.operational_metric_namespace
    value         = "$.providers.recent_failure_count"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "legal_data_failures" {
  name           = "${local.name_prefix}-legal-data-failures"
  pattern        = "{ $.event_type = \"operational_health\" }"
  log_group_name = aws_cloudwatch_log_group.operational_health.name

  metric_transformation {
    name          = "LegalDataIssueCount"
    namespace     = local.operational_metric_namespace
    value         = "$.legal_data.issue_count"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_sns_topic" "operational_alerts" {
  name              = "${local.name_prefix}-operational-alerts"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "operational_email" {
  count = var.operational_alert_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.operational_alerts.arn
  protocol  = "email"
  endpoint  = var.operational_alert_email
}

resource "aws_cloudwatch_metric_alarm" "operational_heartbeat_missing" {
  alarm_name          = "${local.name_prefix}-operational-heartbeat-missing"
  alarm_description   = "Operational health monitor has stopped emitting snapshots."
  namespace           = local.operational_metric_namespace
  metric_name         = "MonitorHeartbeat"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = var.operational_heartbeat_missing_periods
  datapoints_to_alarm = var.operational_heartbeat_missing_periods
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.operational_alerts.arn]
  ok_actions          = [aws_sns_topic.operational_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "queue_oldest_age" {
  alarm_name          = "${local.name_prefix}-queue-oldest-age"
  alarm_description   = "Oldest queued analysis item exceeded the provisional pilot threshold."
  namespace           = local.operational_metric_namespace
  metric_name         = "QueueOldestAgeSeconds"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = var.operational_queue_age_threshold_seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operational_alerts.arn]
  ok_actions          = [aws_sns_topic.operational_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "stale_running" {
  alarm_name          = "${local.name_prefix}-stale-running"
  alarm_description   = "One or more running work items have a stale lease."
  namespace           = local.operational_metric_namespace
  metric_name         = "StaleRunningCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = var.operational_stale_running_threshold_count
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operational_alerts.arn]
  ok_actions          = [aws_sns_topic.operational_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "worker_failures" {
  alarm_name          = "${local.name_prefix}-worker-failures"
  alarm_description   = "Worker final failures were observed in the monitoring window."
  namespace           = local.operational_metric_namespace
  metric_name         = "RecentWorkerFailureCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = var.operational_worker_failure_threshold_count
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operational_alerts.arn]
  ok_actions          = [aws_sns_topic.operational_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "provider_failures" {
  alarm_name          = "${local.name_prefix}-provider-failures"
  alarm_description   = "External provider failures were observed in the monitoring window."
  namespace           = local.operational_metric_namespace
  metric_name         = "RecentProviderFailureCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = var.operational_provider_failure_threshold_count
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operational_alerts.arn]
  ok_actions          = [aws_sns_topic.operational_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "legal_data_failures" {
  alarm_name          = "${local.name_prefix}-legal-data-failures"
  alarm_description   = "Legal data is missing, stale, invalid, or has a failed source."
  namespace           = local.operational_metric_namespace
  metric_name         = "LegalDataIssueCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = var.operational_legal_failure_threshold_count
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operational_alerts.arn]
  ok_actions          = [aws_sns_topic.operational_alerts.arn]
}
