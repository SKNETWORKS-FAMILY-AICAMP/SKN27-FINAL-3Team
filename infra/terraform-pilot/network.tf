data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "pilot" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${local.name_prefix}-vpc" }
}

resource "aws_internet_gateway" "pilot" {
  vpc_id = aws_vpc.pilot.id
  tags   = { Name = "${local.name_prefix}-igw" }
}

resource "aws_subnet" "public_app" {
  vpc_id                  = aws_vpc.pilot.id
  availability_zone       = data.aws_availability_zones.available.names[0]
  cidr_block              = "10.42.0.0/24"
  map_public_ip_on_launch = true

  tags = { Name = "${local.name_prefix}-public-app" }
}

resource "aws_subnet" "database_a" {
  vpc_id            = aws_vpc.pilot.id
  availability_zone = data.aws_availability_zones.available.names[0]
  cidr_block        = "10.42.10.0/24"

  tags = { Name = "${local.name_prefix}-database-a" }
}

resource "aws_subnet" "database_b" {
  vpc_id            = aws_vpc.pilot.id
  availability_zone = data.aws_availability_zones.available.names[1]
  cidr_block        = "10.42.11.0/24"

  tags = { Name = "${local.name_prefix}-database-b" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.pilot.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.pilot.id
  }

  tags = { Name = "${local.name_prefix}-public" }
}

resource "aws_route_table_association" "public_app" {
  subnet_id      = aws_subnet.public_app.id
  route_table_id = aws_route_table.public.id
}
