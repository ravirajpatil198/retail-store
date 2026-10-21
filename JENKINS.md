# Jenkins CI/CD

This pipeline checks the five services, builds their Docker images, publishes
commit-tagged images to Amazon ECR, and updates the Helm values watched by
Argo CD. Argo CD performs the Kubernetes rollout after it sees the values
commit on `main`; Jenkins does not need cluster-admin credentials.

## Jenkins setup

1. Create a **Multibranch Pipeline** for the GitHub repository with a webhook
   trigger. The repository's Argo CD applications currently watch the `main`
   branch.
2. Configure a Linux agent with the label `linux-docker`, a working Docker
   daemon, and these tools on `PATH`:
   - Java 21
   - Go 1.24.4 or later
   - Node.js 20 and Yarn Classic 1.22
   - AWS CLI v2, Helm 3, Python 3, and Git
   The Go catalog tests and checkout integration tests use Testcontainers, so
   the agent must allow builds to access its Docker daemon.
3. Install Jenkins Pipeline, Git, SSH Agent, and JUnit plugins.
4. Set `AWS_ACCOUNT_ID` and `AWS_REGION` in the Jenkins folder or agent
   environment. Attach an AWS IAM role to the agent rather than storing AWS
   access keys in the repository or Jenkinsfile.
5. Create these ECR repositories in that account and region:
   `retail-store-ui`, `retail-store-catalog`, `retail-store-cart`,
   `retail-store-checkout`, and `retail-store-orders`. Configure tag
   mutability as **Immutable**. The agent's IAM role needs
   `ecr:GetAuthorizationToken` plus `ecr:DescribeImages` and ECR image upload
   permissions (`ecr:BatchCheckLayerAvailability`,
   `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`,
   `ecr:CompleteLayerUpload`, and `ecr:PutImage`) for those repositories.
6. Add a Jenkins SSH private-key credential with the ID
   `gitops-ssh-key`. Its GitHub deploy key or machine-user key must be allowed
   to push to `main`. Ensure the checkout's `origin` is the same GitHub
   repository that Argo CD tracks and that the Jenkins agent trusts GitHub's
   SSH host key.
7. Ensure the EKS worker role can pull from those ECR repositories, or
   configure the Kubernetes image-pull secret referenced by the service Helm
   charts.

## Pipeline behavior

- Every branch runs Helm lint, Go tests, Maven tests, and checkout lint/build
  and integration tests.
- Only `main` publishes images. Each image is tagged with the 12-character
  source commit hash, and the service chart values are updated to those
  immutable ECR tags. If a retry finds an image already published for that
  commit, it reuses the image rather than attempting to overwrite the tag.
- Jenkins pushes the chart-values commit to `main`. The resulting
  chart-only build does not publish images again, avoiding a push loop.
- The first `main` build publishes all five images. Later builds publish when
  files under `src/` change.
- Repository URLs, AWS account, region, and the GitOps branch are not
  credentials: review them when adapting this pipeline to another account or
  branch. If Argo CD watches a different branch, update both the pipeline's
  publish condition/push ref and the Argo CD application `targetRevision`.
