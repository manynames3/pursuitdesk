# Teardown

Use teardown when the demo stack is no longer needed or when you want to avoid ongoing AWS cost.

## Before Destroy

- Confirm no customer data or proposal drafts need to be retained.
- Export or snapshot RDS data if needed.
- Confirm local `.tfvars` files and secrets are not committed.

## Destroy AWS Stack

```bash
terraform -chdir=infra/terraform destroy
```

## Cloudflare Pages

Cloudflare Pages is managed outside Terraform. Remove the Pages project manually from Cloudflare if it is no longer needed.

## Secrets

Secrets Manager ARNs may reference secrets created outside Terraform. Delete unused SAM.gov and Stripe secrets manually if they are not shared with another environment.

## Local Cleanup

```bash
rm -rf dist/ build/ .terraform/
```

Do not delete Terraform state unless the stack has been destroyed or state is intentionally migrated.
