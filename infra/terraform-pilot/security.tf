resource "aws_security_group" "app" {
  name        = "${local.name_prefix}-app"
  description = "Public HTTP(S) only; administration uses SSM, never SSH"
  vpc_id      = aws_vpc.pilot.id

  tags = { Name = "${local.name_prefix}-app" }
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  for_each = toset(var.http_ingress_cidrs)

  security_group_id = aws_security_group.app.id
  description       = "Caddy HTTP and ACME redirect"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  for_each = toset(var.http_ingress_cidrs)

  security_group_id = aws_security_group.app.id
  description       = "Caddy HTTPS"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "database" {
  name        = "${local.name_prefix}-database"
  description = "PostgreSQL only from the pilot EC2 security group"
  vpc_id      = aws_vpc.pilot.id

  tags = { Name = "${local.name_prefix}-database" }
}

resource "aws_vpc_security_group_ingress_rule" "database_from_app" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.app.id
  description                  = "PostgreSQL from the pilot application host"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_egress_rule" "database_all" {
  security_group_id = aws_security_group.database.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
