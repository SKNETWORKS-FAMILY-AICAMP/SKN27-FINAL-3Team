resource "aws_db_subnet_group" "pilot" {
  name = "${local.name_prefix}-database"
  subnet_ids = [
    aws_subnet.database_a.id,
    aws_subnet.database_b.id,
  ]

  tags = { Name = "${local.name_prefix}-database" }
}

resource "aws_db_parameter_group" "postgres" {
  name   = "${local.name_prefix}-postgres16"
  family = "postgres16"

  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "immediate"
  }
}

resource "random_id" "final_snapshot" {
  byte_length = 4
}

resource "aws_secretsmanager_secret" "app_database" {
  name                    = "${local.name_prefix}/app-database"
  description             = "Least-privilege PostgreSQL application credential; populated only by the database maintenance workflow."
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-app-database" }
}

resource "aws_db_instance" "postgres" {
  identifier = "${local.name_prefix}-postgres"

  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = var.database_instance_class
  db_name                     = var.database_name
  username                    = var.database_username
  manage_master_user_password = true

  allocated_storage     = var.database_allocated_storage_gib
  max_allocated_storage = var.database_max_allocated_storage_gib
  storage_type          = "gp3"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.pilot.name
  parameter_group_name   = aws_db_parameter_group.postgres.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 7
  backup_window           = "17:00-17:30"
  maintenance_window      = "sun:18:00-sun:18:30"

  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true
  deletion_protection        = var.database_deletion_protection
  skip_final_snapshot        = var.database_skip_final_snapshot
  final_snapshot_identifier  = var.database_skip_final_snapshot ? null : "${local.name_prefix}-final-${random_id.final_snapshot.hex}"

  apply_immediately = false

  tags = { Name = "${local.name_prefix}-postgres" }
}
