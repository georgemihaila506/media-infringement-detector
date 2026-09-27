# AWS resources for week 11 (plan section 7). Every resource is tagged project=infringement.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project = "infringement"
    }
  }
}
