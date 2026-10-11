locals {
  vpc_enabled_lambda_functions = {
    for name, fn in var.lambda_functions : name => fn
    if fn.vpc_enabled
  }
  create_lambda_vpc = length(local.vpc_enabled_lambda_functions) > 0
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "demo" {
  count = local.create_lambda_vpc ? 1 : 0

  cidr_block                       = var.vpc_cidr
  assign_generated_ipv6_cidr_block = true
  enable_dns_hostnames             = true
  enable_dns_support               = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_internet_gateway" "demo" {
  count = local.create_lambda_vpc ? 1 : 0

  vpc_id = aws_vpc.demo[0].id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

resource "aws_egress_only_internet_gateway" "demo" {
  count = local.create_lambda_vpc ? 1 : 0

  vpc_id = aws_vpc.demo[0].id

  tags = {
    Name = "${local.name_prefix}-eigw"
  }
}

resource "aws_subnet" "public" {
  count = local.create_lambda_vpc ? length(var.public_subnet_cidrs) : 0

  vpc_id                          = aws_vpc.demo[0].id
  availability_zone               = data.aws_availability_zones.available.names[count.index]
  cidr_block                      = var.public_subnet_cidrs[count.index]
  ipv6_cidr_block                 = cidrsubnet(aws_vpc.demo[0].ipv6_cidr_block, 8, count.index)
  assign_ipv6_address_on_creation = true

  # Public IPv4 addresses now carry a direct hourly charge. The subnet is public
  # by route table, but launched resources do not auto-receive public IPv4s.
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name_prefix}-public-${count.index + 1}"
    Tier = "public-no-nat"
  }
}

resource "aws_route_table" "public" {
  count = local.create_lambda_vpc ? 1 : 0

  vpc_id = aws_vpc.demo[0].id

  # IPv4 public routing is available for resources that explicitly need it, but
  # no NAT Gateway or Elastic IP is created anywhere in this stack.
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.demo[0].id
  }

  # VPC-attached Lambda functions do not receive public IPv4s. Dual-stack IPv6
  # egress keeps outbound HTTPS possible without a NAT Gateway for IPv6-capable
  # targets such as Cloudflare and AWS dual-stack service endpoints.
  route {
    ipv6_cidr_block        = "::/0"
    egress_only_gateway_id = aws_egress_only_internet_gateway.demo[0].id
  }

  tags = {
    Name = "${local.name_prefix}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count = local.create_lambda_vpc ? length(aws_subnet.public) : 0

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

resource "aws_security_group" "lambda" {
  count = local.create_lambda_vpc ? 1 : 0

  name        = "${local.name_prefix}-lambda-sg"
  description = "Optional Lambda VPC SG: no inbound traffic, bounded outbound HTTPS and PostgreSQL."
  vpc_id      = aws_vpc.demo[0].id

  ingress = []

  egress {
    description = "Allow HTTPS egress; no NAT Gateway is provisioned for IPv4 internet routing."
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description      = "Allow no-NAT HTTPS egress over IPv6 from dual-stack Lambda subnets."
    from_port        = 443
    to_port          = 443
    protocol         = "tcp"
    ipv6_cidr_blocks = ["::/0"]
  }

  egress {
    description = "Allow optional VPC-attached Lambda functions to reach external PostgreSQL over TCP."
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description      = "Allow optional VPC-attached Lambda functions to reach external PostgreSQL over IPv6."
    from_port        = 5432
    to_port          = 5432
    protocol         = "tcp"
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = {
    Name = "${local.name_prefix}-lambda-sg"
  }
}
